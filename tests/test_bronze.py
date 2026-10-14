"""Bronze (landing) tests - run after 10_extract_bronze.

Bronze is a faithful copy of the source, so it is only blocked when the EXTRACT is broken
(missing/empty tables, missing columns, row counts different from MySQL, duplicated primary keys
that would break the MERGE statements downstream). Bad VALUES coming from the source are only reported.
"""
import pytest

from data_checks import WARNING, Check, as_params, foreign_key, run_check, unique

# table -> (primary key, columns used by the pipeline)
LANDING_TABLES = {
    "car": (["car_id"], ["car_id", "producer", "model", "rental_rate", "last_update"]),
    "inventory": (["inventory_id"], ["inventory_id", "car_id", "production_year", "fuel_type", "license_plates",
                                     "purchase_price", "sell_price", "last_update"]),
    "inventory_equipment": (["inventory_id", "equipment_id"], ["inventory_id", "equipment_id"]),
    "equipment": (["equipment_id"], ["equipment_id", "name", "type", "version"]),
    "customer": (["customer_id"], ["customer_id", "first_name", "last_name", "email", "birth_date", "address_id",
                                   "last_update"]),
    "address": (["address_id"], ["address_id", "address", "address2", "city_id", "postal_code", "last_update"]),
    "city": (["city_id"], ["city_id", "city", "country_id"]),
    "country": (["country_id"], ["country_id", "country"]),
    "store": (["store_id"], ["store_id", "store_manager_id", "address_id", "last_update"]),
    "staff": (["staff_id"], ["staff_id", "first_name", "last_name", "email", "address_id", "store_id", "hired_date",
                             "manager_id", "last_update"]),
    "rental": (["rental_id"], ["rental_id", "rental_date", "return_date", "inventory_id", "customer_id", "staff_id",
                               "rental_rate", "payment_deadline"]),
    "payment": (None, ["rental_id", "payment_date", "amount"]),
    "service": (["service_id"], ["service_id", "inventory_id", "service_date", "service_type", "service_cost"]),
}


# --- extract structure -----------------------------------------------------------------------------------------

@pytest.mark.critical
@pytest.mark.parametrize("table", LANDING_TABLES)
def test_table_exists_and_not_empty(spark, table):
    assert spark.catalog.tableExists(f"landing.{table}"), f"landing.{table} does not exist"
    assert spark.table(f"landing.{table}").limit(1).count() == 1, f"landing.{table} is empty"


@pytest.mark.critical
@pytest.mark.parametrize("table", LANDING_TABLES)
def test_required_columns_present(spark, table):
    actual = {c.lower() for c in spark.table(f"landing.{table}").columns}
    missing = [c for c in LANDING_TABLES[table][1] if c.lower() not in actual]
    assert not missing, f"landing.{table} is missing columns used by the pipeline: {missing}"


@pytest.fixture(scope="module")
def mysql_reader(spark):
    try:
        from config import MYSQL_HOST, MYSQL_PASSWORD, MYSQL_USER
    except ImportError:
        pytest.skip("config.py with MySQL credentials not found - skipping source reconciliation")

    def read(query):
        return (spark.read.format("jdbc")
                .option("url", f"jdbc:mysql://{MYSQL_HOST}:3306/wheelie")
                .option("user", MYSQL_USER)
                .option("password", MYSQL_PASSWORD)
                .option("query", query)
                .load())
    return read


@pytest.mark.critical
@pytest.mark.parametrize("table", LANDING_TABLES)
def test_row_count_matches_mysql(spark, mysql_reader, table):
    source_count = mysql_reader(f"SELECT COUNT(*) AS cnt FROM {table}").collect()[0]["cnt"]
    landing_count = spark.table(f"landing.{table}").count()
    assert landing_count == source_count, f"landing.{table}: {landing_count} rows, MySQL: {source_count} rows"


# --- SQL checks ------------------------------------------------------------------------------------------------

CHECKS = [
    # duplicated primary keys break the MERGE statements in silver/gold ("multiple source rows matched")
    *[unique(f"BK{i:02d}", f"landing.{table}", pk)
      for i, (table, (pk, _)) in enumerate(LANDING_TABLES.items(), start=1) if pk],

    # business agreement: exactly one payment per rental - the fact_rental MERGE in 30_load_gold relies on it
    Check("L01", "landing.payment: at most one payment per rental", """
        SELECT rental_id, COUNT(*) AS payments FROM landing.payment GROUP BY rental_id HAVING COUNT(*) > 1"""),

    # source data issues - reported, not blocking
    foreign_key("L02", "landing.payment", "rental_id", "landing.rental", "rental_id", WARNING),
    Check("L03", "landing.rental: return_date < rental_date or return_date missing", """
        SELECT * FROM landing.rental WHERE return_date IS NULL OR return_date < rental_date""", WARNING),
    foreign_key("L04", "landing.inventory", "car_id", "landing.car", "car_id", WARNING),
    foreign_key("L05", "landing.customer", "address_id", "landing.address", "address_id", WARNING),
    foreign_key("L06", "landing.staff", "address_id", "landing.address", "address_id", WARNING),
    foreign_key("L07", "landing.store", "address_id", "landing.address", "address_id", WARNING),
    foreign_key("L08", "landing.address", "city_id", "landing.city", "city_id", WARNING),
    foreign_key("L09", "landing.city", "country_id", "landing.country", "country_id", WARNING),
    foreign_key("L10", "landing.rental", "inventory_id", "landing.inventory", "inventory_id", WARNING),
    foreign_key("L11", "landing.rental", "customer_id", "landing.customer", "customer_id", WARNING),
    foreign_key("L12", "landing.rental", "staff_id", "landing.staff", "staff_id", WARNING),
    foreign_key("L13", "landing.service", "inventory_id", "landing.inventory", "inventory_id", WARNING),
    foreign_key("L14", "landing.inventory_equipment", "equipment_id", "landing.equipment", "equipment_id", WARNING),
    foreign_key("L15", "landing.staff", "manager_id", "landing.staff", "staff_id", WARNING),
    Check("L16", "landing.rental/service: dates in the future", """
        SELECT 'rental' AS tbl, rental_id AS id, rental_date AS dt FROM landing.rental WHERE rental_date > current_date()
        UNION ALL
        SELECT 'service', service_id, service_date FROM landing.service WHERE service_date > current_date()""",
          WARNING),
]


@pytest.mark.parametrize("check", as_params(CHECKS))
def test_bronze(spark, check):
    run_check(spark, check)