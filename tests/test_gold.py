"""Gold (dw) tests - run after 03_load_gold, before the data is consumed by reports.

Verifies the dimensional model itself (keys, foreign keys, SCD2 history, computed measures, date dimensions,
bridge tables) and reconciles it end to end with the source (landing).
"""
import pytest

from data_checks import WARNING, Check, as_params, foreign_key, not_null, run_check, unique

MISSING_RENTALS_DIAGNOSTIC = """
    SELECT reason, COUNT(*) AS rentals
    FROM (
      SELECT CASE
          WHEN cu.customer_key IS NULL THEN 'no active customer in dim_customer'
          WHEN ca.car_key IS NULL THEN 'no active car in dim_car'
          WHEN st.staff_key IS NULL THEN 'no staff member in dim_staff'
          WHEN so.store_key IS NULL THEN 'no active store for the staff member in dim_store'
          WHEN ieg.inventory_id IS NULL THEN 'car without equipment (missing from staging.inventory_equipment_groups)'
          WHEN eg.equipment_group_key IS NULL THEN 'no active group in dim_equipment_group'
          WHEN dt.rental_date_key IS NULL THEN 'date missing from dim_rental_date'
          ELSE 'other reason'
        END AS reason
      FROM landing.rental r
      LEFT JOIN dw.fact_rental f ON f.rental_id = r.rental_id
      LEFT JOIN dw.dim_customer cu ON cu.customer_id = r.customer_id AND cu.is_active = TRUE
      LEFT JOIN dw.dim_car ca ON ca.car_inventory_id = r.inventory_id AND ca.is_active = TRUE
      LEFT JOIN dw.dim_staff st ON st.staff_id = r.staff_id
      LEFT JOIN dw.dim_store so ON so.store_id = st.staff_store_id AND so.is_active = TRUE
      LEFT JOIN staging.inventory_equipment_groups ieg ON ieg.inventory_id = r.inventory_id
      LEFT JOIN dw.dim_equipment_group eg ON eg.equipment_group_id = ieg.eq_group_id AND eg.is_active = TRUE
      LEFT JOIN dw.dim_rental_date dt ON dt.rental_date = r.rental_date
      WHERE f.rental_id IS NULL
    ) x
    GROUP BY reason
    ORDER BY rentals DESC"""

# ---------------------------------------------------------------------------------------------------------------
# 1. Completeness - end-to-end reconciliation of the source (landing) with the warehouse (dw)
# ---------------------------------------------------------------------------------------------------------------
COMPLETENESS = [
    Check("C01", "Every landing.rental has a row in dw.fact_rental", """
        SELECT r.* FROM landing.rental r
        LEFT JOIN dw.fact_rental f ON f.rental_id = r.rental_id
        WHERE f.rental_id IS NULL""", diagnostic_sql=MISSING_RENTALS_DIAGNOSTIC),
    Check("C02", "Every landing.service has a row in dw.fact_service", """
        SELECT s.* FROM landing.service s
        LEFT JOIN dw.fact_service f ON f.service_id = s.service_id
        WHERE f.service_id IS NULL"""),
    Check("C03", "Every landing.inventory has an active version in dw.dim_car", """
        SELECT i.* FROM landing.inventory i
        LEFT JOIN dw.dim_car d ON d.car_inventory_id = i.inventory_id AND d.is_active = TRUE
        WHERE d.car_key IS NULL"""),
    Check("C04", "Every landing.customer has an active version in dw.dim_customer", """
        SELECT c.* FROM landing.customer c
        LEFT JOIN dw.dim_customer d ON d.customer_id = c.customer_id AND d.is_active = TRUE
        WHERE d.customer_key IS NULL"""),
    Check("C05", "Every landing.store has an active version in dw.dim_store", """
        SELECT s.* FROM landing.store s
        LEFT JOIN dw.dim_store d ON d.store_id = s.store_id AND d.is_active = TRUE
        WHERE d.store_key IS NULL"""),
    Check("C06", "Every landing.staff row is in dw.dim_staff", """
        SELECT s.* FROM landing.staff s
        LEFT JOIN dw.dim_staff d ON d.staff_id = s.staff_id
        WHERE d.staff_key IS NULL"""),
    Check("C07", "Every manager (landing.staff.manager_id) is in dw.dim_manager", """
        SELECT DISTINCT s.manager_id FROM landing.staff s
        LEFT JOIN dw.dim_manager d ON d.manager_id = s.manager_id
        WHERE s.manager_id IS NOT NULL AND d.manager_key IS NULL"""),
    Check("C08", "Every landing.equipment row is in dw.dim_equipment", """
        SELECT e.* FROM landing.equipment e
        LEFT JOIN dw.dim_equipment d ON d.equipment_id = e.equipment_id
        WHERE d.equipment_key IS NULL"""),
    Check("C09", "Row count fact_rental = landing.rental", """
        SELECT src_cnt, dw_cnt FROM (
          SELECT (SELECT COUNT(*) FROM landing.rental) AS src_cnt,
                 (SELECT COUNT(*) FROM dw.fact_rental) AS dw_cnt)
        WHERE src_cnt <> dw_cnt"""),
    Check("C10", "Row count fact_service = landing.service", """
        SELECT src_cnt, dw_cnt FROM (
          SELECT (SELECT COUNT(*) FROM landing.service) AS src_cnt,
                 (SELECT COUNT(*) FROM dw.fact_service) AS dw_cnt)
        WHERE src_cnt <> dw_cnt"""),
    Check("C11", "Payment total: landing.payment = fact_rental.payment_amount", """
        SELECT src_sum, dw_sum, src_sum - dw_sum AS diff FROM (
          SELECT (SELECT COALESCE(SUM(p.amount), 0) FROM landing.payment p
                  WHERE p.rental_id IN (SELECT rental_id FROM landing.rental)) AS src_sum,
                 (SELECT COALESCE(SUM(payment_amount), 0) FROM dw.fact_rental) AS dw_sum)
        WHERE src_sum <> dw_sum"""),
    Check("C12", "Service cost total: landing.service = fact_service.service_cost", """
        SELECT src_sum, dw_sum, src_sum - dw_sum AS diff FROM (
          SELECT (SELECT COALESCE(SUM(service_cost), 0) FROM landing.service) AS src_sum,
                 (SELECT COALESCE(SUM(service_cost), 0) FROM dw.fact_service) AS dw_sum)
        WHERE src_sum <> dw_sum"""),
    Check("C13", "Every rental date is in dw.dim_rental_date", """
        SELECT DISTINCT r.rental_date FROM landing.rental r
        LEFT JOIN dw.dim_rental_date d ON d.rental_date = r.rental_date
        WHERE d.rental_date IS NULL"""),
    Check("C14", "Every service date is in dw.dim_service_date", """
        SELECT DISTINCT s.service_date FROM landing.service s
        LEFT JOIN dw.dim_service_date d ON d.service_date = s.service_date
        WHERE d.service_date IS NULL"""),
]

# ---------------------------------------------------------------------------------------------------------------
# 2. Key uniqueness
# ---------------------------------------------------------------------------------------------------------------
UNIQUENESS = [
    # surrogate keys
    unique("U01", "dw.dim_car", ["car_key"]),
    unique("U02", "dw.dim_customer", ["customer_key"]),
    unique("U03", "dw.dim_store", ["store_key"]),
    unique("U04", "dw.dim_staff", ["staff_key"]),
    unique("U05", "dw.dim_manager", ["manager_key"]),
    unique("U06", "dw.dim_equipment", ["equipment_key"]),
    unique("U07", "dw.dim_equipment_group", ["equipment_group_key"]),
    unique("U08", "dw.dim_rental_date", ["rental_date_key"]),
    unique("U09", "dw.dim_service_date", ["service_date_key"]),
    unique("U10", "dw.fact_rental", ["rental_key"]),
    unique("U11", "dw.fact_service", ["service_key"]),
    # business keys - facts and SCD1 dimensions
    unique("U12", "dw.fact_rental", ["rental_id"]),  # also catches multiple payments per rental
    unique("U13", "dw.fact_service", ["service_id"]),
    unique("U14", "dw.dim_staff", ["staff_id"]),
    unique("U15", "dw.dim_manager", ["manager_id"]),
    unique("U16", "dw.dim_equipment", ["equipment_id"]),
    unique("U17", "dw.dim_equipment_group", ["equipment_group_id"]),
    unique("U18", "dw.dim_rental_date", ["rental_date"]),
    unique("U19", "dw.dim_service_date", ["service_date"]),
    unique("U20", "dw.calendar", ["calendar_date"]),
    # SCD2 - at most one active version per business key
    unique("U21", "dw.dim_car", ["car_inventory_id"], where="is_active = TRUE"),
    unique("U22", "dw.dim_customer", ["customer_id"], where="is_active = TRUE"),
    unique("U23", "dw.dim_store", ["store_id"], where="is_active = TRUE"),
    # bridge tables
    unique("U24", "dw.bridge_staff_hierarchy", ["staff_key", "manager_key"]),
    unique("U25", "dw.bridge_equipment_group_equipment", ["equipment_group_key", "equipment_key"]),
    unique("U26", "dw.dim_car", ["car_license_plates"], where="is_active = TRUE", severity=WARNING),
]

# ---------------------------------------------------------------------------------------------------------------
# 3. Required values (NOT NULL)
# ---------------------------------------------------------------------------------------------------------------
NOT_NULL = [
    not_null("N01", "dw.fact_rental", ["customer_key", "car_key", "store_key", "staff_key", "eqipment_group_key",
                                       "rental_date_key", "return_date", "payment_date", "payment_deadline"]),
    not_null("N02", "dw.fact_service", ["car_key", "service_date_key", "service_type", "service_cost"]),
    not_null("N03", "dw.dim_car", ["car_producer", "car_model", "car_production_year",
                                   "car_current_rental_rate", "valid_from", "valid_to", "is_active"]),
    not_null("N04", "dw.dim_car", ["car_fuel_type", "car_purchase_price"], WARNING),
    not_null("N05", "dw.dim_customer", ["customer_first_name", "customer_last_name", "valid_from", "valid_to",
                                        "is_active"]),
    not_null("N06", "dw.dim_customer", ["customer_email", "customer_birth_date", "customer_postal_code"], WARNING),
    not_null("N07", "dw.dim_store", ["valid_from", "valid_to", "is_active", "store_manager_id"]),
    # CONCAT(address, ', ', address2) returns NULL when address2 is NULL
    not_null("N08", "dw.dim_store", ["store_address"], WARNING),
    not_null("N09", "dw.dim_staff", ["staff_address"], WARNING),
    not_null("N10", "dw.dim_manager", ["manager_address"], WARNING),
    not_null("N11", "dw.dim_staff", ["staff_first_name", "staff_last_name", "staff_store_id"]),
    not_null("N12", "dw.dim_equipment", ["equipment_name", "equipment_type"]),
    Check("N13", "Placeholder 'NA' in addresses (city/country missing from lookups)", """
        SELECT 'dim_customer' AS tbl, customer_id AS id, customer_city AS city, customer_country AS country
          FROM dw.dim_customer WHERE customer_city = 'NA' OR customer_country = 'NA'
        UNION ALL
        SELECT 'dim_store', store_id, store_city, store_country
          FROM dw.dim_store WHERE store_city = 'NA' OR store_country = 'NA'
        UNION ALL
        SELECT 'dim_staff', staff_id, staff_city, staff_country
          FROM dw.dim_staff WHERE staff_city = 'NA' OR staff_country = 'NA'
        UNION ALL
        SELECT 'dim_manager', manager_id, manager_city, manager_country
          FROM dw.dim_manager WHERE manager_city = 'NA' OR manager_country = 'NA'""", WARNING),
]

# ---------------------------------------------------------------------------------------------------------------
# 4. Referential integrity
# ---------------------------------------------------------------------------------------------------------------
REFERENTIAL_INTEGRITY = [
    foreign_key("F01", "dw.fact_rental", "customer_key", "dw.dim_customer", "customer_key"),
    foreign_key("F02", "dw.fact_rental", "car_key", "dw.dim_car", "car_key"),
    foreign_key("F03", "dw.fact_rental", "store_key", "dw.dim_store", "store_key"),
    foreign_key("F04", "dw.fact_rental", "staff_key", "dw.dim_staff", "staff_key"),
    foreign_key("F05", "dw.fact_rental", "eqipment_group_key", "dw.dim_equipment_group", "equipment_group_key"),
    foreign_key("F06", "dw.fact_rental", "rental_date_key", "dw.dim_rental_date", "rental_date_key"),
    foreign_key("F07", "dw.fact_service", "car_key", "dw.dim_car", "car_key"),
    foreign_key("F08", "dw.fact_service", "service_date_key", "dw.dim_service_date", "service_date_key"),
    foreign_key("F09", "dw.bridge_staff_hierarchy", "staff_key", "dw.dim_staff", "staff_key"),
    foreign_key("F10", "dw.bridge_staff_hierarchy", "manager_key", "dw.dim_manager", "manager_key"),
    foreign_key("F11", "dw.bridge_equipment_group_equipment", "equipment_group_key",
                "dw.dim_equipment_group", "equipment_group_key"),
    foreign_key("F12", "dw.bridge_equipment_group_equipment", "equipment_key", "dw.dim_equipment", "equipment_key"),
    foreign_key("F13", "dw.dim_rental_date", "rental_date", "dw.calendar", "calendar_date"),
    foreign_key("F14", "dw.dim_service_date", "service_date", "dw.calendar", "calendar_date"),
    foreign_key("F15", "dw.dim_staff", "staff_store_id", "landing.store", "store_id", WARNING),
    foreign_key("F16", "dw.dim_store", "store_manager_id", "landing.staff", "staff_id", WARNING),
    Check("F17", "Rental fact points to the correct business keys (rental vs dimensions)", """
        SELECT f.rental_id, r.customer_id, cu.customer_id AS dw_customer_id,
               r.inventory_id, ca.car_inventory_id AS dw_inventory_id,
               r.staff_id, st.staff_id AS dw_staff_id,
               r.rental_date, d.rental_date AS dw_rental_date
        FROM dw.fact_rental f
        JOIN landing.rental r ON r.rental_id = f.rental_id
        JOIN dw.dim_customer cu ON cu.customer_key = f.customer_key
        JOIN dw.dim_car ca ON ca.car_key = f.car_key
        JOIN dw.dim_staff st ON st.staff_key = f.staff_key
        JOIN dw.dim_rental_date d ON d.rental_date_key = f.rental_date_key
        WHERE r.customer_id <> cu.customer_id OR r.inventory_id <> ca.car_inventory_id
           OR r.staff_id <> st.staff_id OR r.rental_date <> d.rental_date"""),
]

# ---------------------------------------------------------------------------------------------------------------
# 5. SCD2 / SCD1 correctness
# ---------------------------------------------------------------------------------------------------------------
SCD2_DIMENSIONS = {
    "dw.dim_car": ("car_inventory_id", "car_key",
                   ["car_producer", "car_model", "car_production_year", "car_fuel_type", "car_license_plates",
                    "car_current_rental_rate", "car_purchase_price", "car_sell_price"]),
    "dw.dim_customer": ("customer_id", "customer_key",
                        ["customer_first_name", "customer_last_name", "customer_email", "customer_birth_date",
                         "customer_address", "customer_city", "customer_country", "customer_postal_code"]),
    "dw.dim_store": ("store_id", "store_key",
                     ["store_manager_id", "store_address", "store_city", "store_country", "store_postal_code"]),
}


def scd2_checks(n, table, business_key, surrogate_key, attributes):
    attr_hash = ("md5(concat_ws('|', "
                 + ", ".join(f"COALESCE(CAST({a} AS STRING), '<null>')" for a in attributes) + "))")
    versions = f"""
        SELECT {business_key}, {surrogate_key}, valid_from, valid_to, is_active, {attr_hash} AS attr_hash,
               LEAD(valid_from) OVER (PARTITION BY {business_key} ORDER BY valid_from, {surrogate_key}) AS next_valid_from,
               LAG({attr_hash}) OVER (PARTITION BY {business_key} ORDER BY valid_from, {surrogate_key}) AS prev_attr_hash
        FROM {table}"""
    return [
        Check(f"S{n}1", f"{table}: valid_from <= valid_to", f"SELECT * FROM {table} WHERE valid_from > valid_to"),
        Check(f"S{n}2", f"{table}: active version <=> valid_to = 9999-12-31", f"""
            SELECT * FROM {table}
            WHERE (is_active = TRUE  AND CAST(valid_to AS DATE) <> DATE'9999-12-31')
               OR (is_active = FALSE AND CAST(valid_to AS DATE) =  DATE'9999-12-31')"""),
        Check(f"S{n}3", f"{table}: version intervals do not overlap",
              f"SELECT * FROM ({versions}) WHERE next_valid_from < valid_to"),
        Check(f"S{n}4", f"{table}: no gaps between versions",
              f"SELECT * FROM ({versions}) WHERE next_valid_from > valid_to", WARNING),
        Check(f"S{n}5", f"{table}: consecutive versions differ in attributes",
              f"SELECT * FROM ({versions}) WHERE attr_hash = prev_attr_hash"),
    ]


SCD = [
    *[check for n, (table, keys) in enumerate(SCD2_DIMENSIONS.items(), start=1) for check in scd2_checks(n, table, *keys)],
    # active version compared with the source (no unloaded changes)
    Check("S16", "dw.dim_car: active version = staging.car", """
        SELECT s.car_inventory_id FROM staging.car s
        JOIN dw.dim_car d ON d.car_inventory_id = s.car_inventory_id AND d.is_active = TRUE
        WHERE NOT (d.car_producer <=> s.car_producer AND d.car_model <=> s.car_model
               AND d.car_production_year <=> s.car_production_year AND d.car_fuel_type <=> s.car_fuel_type
               AND d.car_license_plates <=> s.car_license_plates
               AND d.car_current_rental_rate <=> s.car_current_rental_rate
               AND d.car_purchase_price <=> s.car_purchase_price AND d.car_sell_price <=> s.car_sell_price)"""),
    Check("S26", "dw.dim_customer: active version = landing.customer", """
        SELECT c.customer_id, c.first_name, d.customer_first_name, c.last_name, d.customer_last_name,
               c.email, d.customer_email, c.birth_date, d.customer_birth_date
        FROM landing.customer c
        JOIN dw.dim_customer d ON d.customer_id = c.customer_id AND d.is_active = TRUE
        WHERE NOT (c.first_name <=> d.customer_first_name AND c.last_name <=> d.customer_last_name
               AND c.email <=> d.customer_email AND c.birth_date <=> d.customer_birth_date)"""),
    Check("S36", "dw.dim_store: active version = landing.store", """
        SELECT s.store_id, s.store_manager_id, d.store_manager_id AS dw_store_manager_id
        FROM landing.store s
        JOIN dw.dim_store d ON d.store_id = s.store_id AND d.is_active = TRUE
        WHERE NOT (s.store_manager_id <=> d.store_manager_id)"""),
    Check("S40", "dw.dim_staff (SCD1) matches landing.staff", """
        SELECT s.staff_id, s.manager_id, d.staff_manager_id, s.store_id, d.staff_store_id, s.email, d.staff_email
        FROM landing.staff s JOIN dw.dim_staff d ON d.staff_id = s.staff_id
        WHERE NOT (s.manager_id <=> d.staff_manager_id AND s.store_id <=> d.staff_store_id
               AND s.email <=> d.staff_email AND s.first_name <=> d.staff_first_name
               AND s.last_name <=> d.staff_last_name)"""),
]

# ---------------------------------------------------------------------------------------------------------------
# 6. Business rules - cars (the cleansing rules are owned by silver; these confirm the gold load kept them)
# ---------------------------------------------------------------------------------------------------------------
CAR_RULES = [
    Check("B01", "dim_car: car_fuel_type in {Diesel, Petrol}", """
        SELECT * FROM dw.dim_car WHERE car_fuel_type NOT IN ('Diesel', 'Petrol')"""),
    Check("B02", "dim_car: production year between 1990 and the current year", """
        SELECT * FROM dw.dim_car
        WHERE car_production_year < 1990 OR car_production_year > YEAR(current_date())"""),
    Check("B03", "No car is rented before its production year", """
        SELECT c.car_inventory_id, c.car_production_year, d.rental_date, f.rental_id
        FROM dw.fact_rental f
        JOIN dw.dim_car c ON c.car_key = f.car_key
        JOIN dw.dim_rental_date d ON d.rental_date_key = f.rental_date_key
        WHERE YEAR(d.rental_date) < c.car_production_year"""),
    Check("B04", "No car is serviced before its production year", """
        SELECT c.car_inventory_id, c.car_production_year, d.service_date, f.service_id
        FROM dw.fact_service f
        JOIN dw.dim_car c ON c.car_key = f.car_key
        JOIN dw.dim_service_date d ON d.service_date_key = f.service_date_key
        WHERE YEAR(d.service_date) < c.car_production_year"""),
]

# ---------------------------------------------------------------------------------------------------------------
# 7. Business rules - measures in fact_rental and fact_service
# ---------------------------------------------------------------------------------------------------------------
FACT_RENTAL_WITH_DATE = """
    SELECT f.*, d.rental_date
    FROM dw.fact_rental f JOIN dw.dim_rental_date d ON d.rental_date_key = f.rental_date_key"""

FACT_RULES = [
    Check("R01", "fact_rental: return_date >= rental_date",
          f"SELECT * FROM ({FACT_RENTAL_WITH_DATE}) WHERE return_date < rental_date"),
    Check("R02", "fact_rental: rental_duration = return_date - rental_date and >= 0", f"""
        SELECT * FROM ({FACT_RENTAL_WITH_DATE})
        WHERE rental_duration <> DATEDIFF(return_date, rental_date) OR rental_duration < 0"""),
    Check("R03", "fact_rental: rental_amount = daily_rental_rate * rental_duration", """
        SELECT * FROM dw.fact_rental WHERE rental_amount <> daily_rental_rate * rental_duration"""),
    Check("R04", "fact_rental: amounts non-negative, rate positive", """
        SELECT * FROM dw.fact_rental
        WHERE rental_amount < 0 OR payment_amount < 0 OR daily_rental_rate <= 0"""),
    Check("R05", "fact_rental: payment_delay_days >= 0", """
        SELECT * FROM dw.fact_rental WHERE payment_delay_days < 0"""),
    Check("R06", "fact_rental: delay of paid rentals = max(0, payment_date - deadline)", """
        SELECT * FROM dw.fact_rental
        WHERE payment_date <> DATE'9999-12-31'
          AND payment_delay_days <> GREATEST(0, DATEDIFF(payment_date, payment_deadline))"""),
    Check("R07", "fact_rental: unpaid => payment_amount = 0", """
        SELECT * FROM dw.fact_rental WHERE payment_date = DATE'9999-12-31' AND payment_amount <> 0"""),
    Check("R08", "fact_rental: amount paid differs from amount due", """
        SELECT * FROM dw.fact_rental
        WHERE payment_date <> DATE'9999-12-31' AND payment_amount <> rental_amount""", WARNING),
    Check("R09", "fact_rental: payment deadline not before the rental date",
          f"SELECT * FROM ({FACT_RENTAL_WITH_DATE}) WHERE payment_deadline < rental_date", WARNING),
    Check("R10", "fact_rental: payment not before the rental date", f"""
        SELECT * FROM ({FACT_RENTAL_WITH_DATE})
        WHERE payment_date <> DATE'9999-12-31' AND payment_date < rental_date""", WARNING),
    Check("R11", "fact_rental: no future dates", f"""
        SELECT * FROM ({FACT_RENTAL_WITH_DATE})
        WHERE rental_date > current_date()
           OR (payment_date <> DATE'9999-12-31' AND payment_date > current_date())""", WARNING),
    Check("R12", "fact_rental: rental longer than 365 days (outlier)", """
        SELECT * FROM dw.fact_rental WHERE rental_duration > 365""", WARNING),
    Check("R13", "fact_rental: daily_rental_rate = rate in landing.rental", """
        SELECT f.rental_id, f.daily_rental_rate, r.rental_rate
        FROM dw.fact_rental f JOIN landing.rental r ON r.rental_id = f.rental_id
        WHERE f.daily_rental_rate <> r.rental_rate"""),
    Check("R14", "fact_service: service_cost > 0 and service_type not blank", """
        SELECT * FROM dw.fact_service WHERE service_cost <= 0 OR TRIM(service_type) = ''"""),
    Check("R15", "fact_service: no future service dates", """
        SELECT f.*, d.service_date FROM dw.fact_service f
        JOIN dw.dim_service_date d ON d.service_date_key = f.service_date_key
        WHERE d.service_date > current_date()""", WARNING),
]

# ---------------------------------------------------------------------------------------------------------------
# 8. Business rules - customers, staff, lookups
# ---------------------------------------------------------------------------------------------------------------
PEOPLE_RULES = [
    Check("P01", "dim_customer: valid e-mail format", """
        SELECT * FROM dw.dim_customer
        WHERE customer_email IS NOT NULL AND NOT customer_email RLIKE '^[^@ ]+@[^@ ]+[.][^@ ]+$'""", WARNING),
    Check("P02", "dim_customer: customer is an adult (>= 18) and younger than 100", """
        SELECT * FROM dw.dim_customer
        WHERE customer_birth_date > add_months(current_date(), -18 * 12)
           OR customer_birth_date < add_months(current_date(), -100 * 12)""", WARNING),
    Check("P03", "Customer was >= 18 on the rental date", """
        SELECT f.rental_id, c.customer_id, c.customer_birth_date, d.rental_date
        FROM dw.fact_rental f
        JOIN dw.dim_customer c ON c.customer_key = f.customer_key
        JOIN dw.dim_rental_date d ON d.rental_date_key = f.rental_date_key
        WHERE c.customer_birth_date > add_months(d.rental_date, -18 * 12)""", WARNING),
    Check("P04", "Unified country name (no 'Czechia' in dimensions)", """
        SELECT 'dim_customer' AS tbl, customer_id AS id FROM dw.dim_customer WHERE customer_country = 'Czechia'
        UNION ALL SELECT 'dim_store',   store_id   FROM dw.dim_store   WHERE store_country   = 'Czechia'
        UNION ALL SELECT 'dim_staff',   staff_id   FROM dw.dim_staff   WHERE staff_country   = 'Czechia'
        UNION ALL SELECT 'dim_manager', manager_id FROM dw.dim_manager WHERE manager_country = 'Czechia'"""),
    Check("P05", "dim_staff/dim_manager: hire date not in the future", """
        SELECT 'dim_staff' AS tbl, staff_id AS id, staff_hired_date AS hired_date
          FROM dw.dim_staff WHERE staff_hired_date > current_date()
        UNION ALL
        SELECT 'dim_manager', manager_id, manager_hired_date
          FROM dw.dim_manager WHERE manager_hired_date > current_date()"""),
    Check("P06", "Staff member handled the rental after their hire date", """
        SELECT f.rental_id, s.staff_id, s.staff_hired_date, d.rental_date
        FROM dw.fact_rental f
        JOIN dw.dim_staff s ON s.staff_key = f.staff_key
        JOIN dw.dim_rental_date d ON d.rental_date_key = f.rental_date_key
        WHERE d.rental_date < s.staff_hired_date""", WARNING),
    Check("P07", "dim_manager: manager data = staff data for the same id", """
        SELECT m.manager_id, m.manager_email, s.staff_email, m.manager_store_id, s.staff_store_id
        FROM dw.dim_manager m JOIN dw.dim_staff s ON s.staff_id = m.manager_id
        WHERE NOT (m.manager_email <=> s.staff_email AND m.manager_store_id <=> s.staff_store_id
               AND m.manager_last_name <=> s.staff_last_name)"""),
]

# ---------------------------------------------------------------------------------------------------------------
# 9. Date dimensions and calendar
# ---------------------------------------------------------------------------------------------------------------
def date_dimension_check(check_id, prefix, extra_conditions=""):
    p = prefix
    return Check(check_id, f"dim_{p}_date: attributes match the date", f"""
        SELECT * FROM dw.dim_{p}_date
        WHERE {p}_date_key <> CAST(date_format({p}_date, 'yyyyMMdd') AS INT)
           OR {p}_calendar_year    <> YEAR({p}_date)
           OR {p}_calendar_quarter <> QUARTER({p}_date)
           OR {p}_calendar_month   <> MONTH({p}_date)
           OR {p}_calendar_day     <> DAY({p}_date)
           OR {p}_day_of_week      <> dayofweek({p}_date)
           OR {p}_week_of_year     <> weekofyear({p}_date)
           OR {p}_days_since_epoch <> DATEDIFF({p}_date, DATE'2000-01-01'){extra_conditions}""")


DATE_DIMENSIONS = [
    Check("D01", "dw.calendar: continuous (no gaps)", """
        SELECT cnt, expected FROM (
          SELECT COUNT(*) AS cnt, DATEDIFF(MAX(calendar_date), MIN(calendar_date)) + 1 AS expected FROM dw.calendar)
        WHERE cnt <> expected"""),
    Check("D02", "dw.calendar: range covers all source dates", """
        SELECT 'rental' AS src, MIN(rental_date) AS min_d, MAX(rental_date) AS max_d FROM landing.rental
        HAVING MIN(rental_date) < (SELECT MIN(calendar_date) FROM dw.calendar)
            OR MAX(rental_date) > (SELECT MAX(calendar_date) FROM dw.calendar)
        UNION ALL
        SELECT 'service', MIN(service_date), MAX(service_date) FROM landing.service
        HAVING MIN(service_date) < (SELECT MIN(calendar_date) FROM dw.calendar)
            OR MAX(service_date) > (SELECT MAX(calendar_date) FROM dw.calendar)"""),
    date_dimension_check("D03", "rental", """
           OR rental_is_weekend = rental_is_working_day
           OR rental_is_weekend <> (dayofweek(rental_date) IN (1, 7))
           OR rental_is_covid <> (rental_date BETWEEN DATE'2020-03-01' AND DATE'2022-02-28')"""),
    date_dimension_check("D04", "service"),
    Check("D05", "dim_rental_date: no dates that are unused in landing.rental", """
        SELECT d.* FROM dw.dim_rental_date d
        LEFT JOIN (SELECT DISTINCT rental_date FROM landing.rental) r ON r.rental_date = d.rental_date
        WHERE r.rental_date IS NULL""", WARNING),
    Check("D06", "dim_service_date: no dates that are unused in landing.service", """
        SELECT d.* FROM dw.dim_service_date d
        LEFT JOIN (SELECT DISTINCT service_date FROM landing.service) s ON s.service_date = d.service_date
        WHERE s.service_date IS NULL""", WARNING),
]

# ---------------------------------------------------------------------------------------------------------------
# 10. Bridge tables: staff hierarchy and equipment groups
# ---------------------------------------------------------------------------------------------------------------
BRIDGES = [
    Check("H01", "Every staff -> direct manager relation has a distance = 1 row", """
        SELECT s.staff_id, s.manager_id
        FROM landing.staff s
        JOIN dw.dim_staff ds   ON ds.staff_id = s.staff_id
        JOIN dw.dim_manager dm ON dm.manager_id = s.manager_id
        LEFT JOIN dw.bridge_staff_hierarchy b
          ON b.staff_key = ds.staff_key AND b.manager_key = dm.manager_key AND b.distance = 1
        WHERE s.manager_id IS NOT NULL AND s.manager_id <> s.staff_id AND b.staff_key IS NULL"""),
    Check("H02", "distance >= 1 and no loops (nobody is their own manager)", """
        SELECT b.*, s.staff_id, m.manager_id
        FROM dw.bridge_staff_hierarchy b
        JOIN dw.dim_staff s   ON s.staff_key = b.staff_key
        JOIN dw.dim_manager m ON m.manager_key = b.manager_key
        WHERE b.distance < 1 OR b.distance IS NULL OR s.staff_id = m.manager_id"""),
    Check("H03", "Bridge has no direct relations (distance = 1) missing from the source", """
        SELECT s.staff_id, m.manager_id
        FROM dw.bridge_staff_hierarchy b
        JOIN dw.dim_staff s   ON s.staff_key = b.staff_key
        JOIN dw.dim_manager m ON m.manager_key = b.manager_key
        LEFT JOIN landing.staff l ON l.staff_id = s.staff_id AND l.manager_id = m.manager_id
        WHERE b.distance = 1 AND l.staff_id IS NULL"""),
    Check("H04", "One distance per (staff, manager) pair", """
        SELECT staff_key, manager_key, COUNT(DISTINCT distance) AS distances
        FROM dw.bridge_staff_hierarchy GROUP BY staff_key, manager_key HAVING COUNT(DISTINCT distance) > 1"""),
    Check("E01", "Every equipment group has >= 1 item in the bridge", """
        SELECT g.* FROM dw.dim_equipment_group g
        LEFT JOIN dw.bridge_equipment_group_equipment b ON b.equipment_group_key = g.equipment_group_key
        WHERE b.equipment_group_key IS NULL"""),
    Check("E02", "Group item count in the bridge = id count in staging.equipment_groups", """
        SELECT g.equipment_group_id, s.eq_ids, SIZE(SPLIT(s.eq_ids, ', ')) AS expected, COUNT(b.equipment_key) AS actual
        FROM dw.dim_equipment_group g
        JOIN staging.equipment_groups s ON s.eq_group_id = g.equipment_group_id
        LEFT JOIN dw.bridge_equipment_group_equipment b ON b.equipment_group_key = g.equipment_group_key
        GROUP BY g.equipment_group_id, s.eq_ids
        HAVING expected <> actual"""),
    Check("E03", "dim_equipment_group matches staging.equipment_groups", """
        SELECT g.equipment_group_id, g.equipment_group_name, s.eq_group_names
        FROM dw.dim_equipment_group g
        LEFT JOIN staging.equipment_groups s ON s.eq_group_id = g.equipment_group_id
        WHERE NOT (g.equipment_group_name <=> s.eq_group_names)"""),
    Check("E04", "Group in the fact = the car's group in staging", """
        SELECT f.rental_id, c.car_inventory_id, g.equipment_group_id, ieg.eq_group_id
        FROM dw.fact_rental f
        JOIN dw.dim_car c ON c.car_key = f.car_key
        JOIN dw.dim_equipment_group g ON g.equipment_group_key = f.eqipment_group_key
        JOIN staging.inventory_equipment_groups ieg ON ieg.inventory_id = c.car_inventory_id
        WHERE g.equipment_group_id <> ieg.eq_group_id"""),
]

CHECKS = (COMPLETENESS + UNIQUENESS + NOT_NULL + REFERENTIAL_INTEGRITY + SCD + CAR_RULES + FACT_RULES
          + PEOPLE_RULES + DATE_DIMENSIONS + BRIDGES)


@pytest.mark.parametrize("check", as_params(CHECKS))
def test_gold(spark, check):
    run_check(spark, check)
