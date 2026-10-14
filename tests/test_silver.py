"""Silver (staging) tests - run after 02_transform_silver, before 03_load_gold.

This is the main gate: it verifies that the cleansing rules from 02_transform_silver were applied
and that staging is internally consistent, so bad data never reaches the gold layer.
"""
import pytest

from data_checks import WARNING, Check, as_params, foreign_key, not_null, run_check, unique

CHECKS = [
    # --- staging.car -------------------------------------------------------------------------------------------
    unique("U01", "staging.car", ["car_inventory_id"]),
    not_null("N01", "staging.car", ["car_id", "car_producer", "car_model", "car_production_year",
                                    "car_current_rental_rate"]),
    not_null("N02", "staging.car", ["car_fuel_type", "car_purchase_price"], WARNING),
    Check("T01", "staging.car: fuel_type normalised to Diesel / Petrol", """
        SELECT * FROM staging.car WHERE car_fuel_type NOT IN ('Diesel', 'Petrol')"""),
    Check("T02", "staging.car: no purchase price of 111", """
        SELECT * FROM staging.car WHERE car_purchase_price = 111"""),
    Check("T03", "staging.car: production year filled in, between 1990 and the current year", """
        SELECT * FROM staging.car
        WHERE car_production_year IS NULL OR car_production_year < 1990
           OR car_production_year > YEAR(current_date())"""),
    Check("T04", "staging.car: rental rate > 0, purchase price > 0, sell price >= 0", """
        SELECT * FROM staging.car
        WHERE car_current_rental_rate <= 0 OR car_purchase_price <= 0 OR car_sell_price < 0"""),
    Check("T05", "staging.car: suspiciously low purchase price (< 1000, cf. the 111 -> 111000 fix)", """
        SELECT * FROM staging.car WHERE car_purchase_price < 1000""", WARNING),
    Check("T06", "staging.car: sell price > purchase price", """
        SELECT * FROM staging.car WHERE car_sell_price > car_purchase_price""", WARNING),
    Check("T07", "staging.car contains every car from landing.inventory", """
        SELECT i.inventory_id FROM landing.inventory i
        LEFT JOIN staging.car s ON s.car_inventory_id = i.inventory_id
        WHERE s.car_inventory_id IS NULL"""),
    Check("T08", "staging.car: uncleansed attributes match landing", """
        SELECT s.car_inventory_id FROM staging.car s
        JOIN landing.inventory i ON i.inventory_id = s.car_inventory_id
        JOIN landing.car c ON c.car_id = i.car_id
        WHERE NOT (s.car_id <=> c.car_id AND s.car_producer <=> c.producer AND s.car_model <=> c.model
               AND s.car_current_rental_rate <=> c.rental_rate AND s.car_license_plates <=> i.license_plates)"""),
    Check("T09", "No car is rented before its production year", """
        SELECT s.car_inventory_id, s.car_production_year, r.rental_id, r.rental_date
        FROM staging.car s JOIN landing.rental r ON r.inventory_id = s.car_inventory_id
        WHERE YEAR(r.rental_date) < s.car_production_year"""),
    unique("U02", "staging.car", ["car_license_plates"], severity=WARNING),

    # --- geography lookups -------------------------------------------------------------------------------------
    unique("U03", "staging.country", ["country_id"]),
    unique("U04", "staging.country", ["LOWER(TRIM(country))"]),  # e.g. Czechia / Czech Republic as duplicates
    unique("U05", "staging.city", ["city_id"]),
    foreign_key("F01", "staging.city", "country_id", "staging.country", "country_id"),
    Check("T10", "staging.country/city: no id 108 (Czechia merged into Czech Republic)", """
        SELECT 'country' AS tbl, country_id FROM staging.country WHERE country_id = 108
        UNION ALL
        SELECT 'city', country_id FROM staging.city WHERE country_id = 108"""),
    Check("T11", "staging.city contains every city from landing", """
        SELECT l.city_id FROM landing.city l LEFT JOIN staging.city s ON s.city_id = l.city_id
        WHERE s.city_id IS NULL"""),
    Check("T12", "Every address points to a city with a country (otherwise 'NA' in gold)", """
        SELECT a.address_id, a.city_id FROM landing.address a
        LEFT JOIN staging.city ci ON ci.city_id = a.city_id
        LEFT JOIN staging.country co ON co.country_id = ci.country_id
        WHERE co.country_id IS NULL""", WARNING),

    # --- equipment groups --------------------------------------------------------------------------------------
    unique("U06", "staging.equipment_groups", ["eq_group_id"]),
    unique("U07", "staging.equipment_groups", ["eq_ids"]),
    unique("U08", "staging.inventory_equipment_groups", ["inventory_id"]),
    Check("E01", "Every car with equipment has a group assigned", """
        SELECT * FROM staging.inventory_equipment_groups WHERE eq_group_id IS NULL"""),
    Check("E02", "Cars without any equipment (their rentals are dropped from fact_rental)", """
        SELECT i.inventory_id FROM landing.inventory i
        LEFT JOIN staging.inventory_equipment_groups g ON g.inventory_id = i.inventory_id
        WHERE g.inventory_id IS NULL""", WARNING),
    foreign_key("F02", "staging.bridge_equipment__equipment_groups", "equipment_id",
                "landing.equipment", "equipment_id"),
    Check("E03", "Group item count in the staging bridge = id count in eq_ids", """
        SELECT g.eq_group_id, g.eq_ids, SIZE(SPLIT(g.eq_ids, ', ')) AS expected, COUNT(b.equipment_id) AS actual
        FROM staging.equipment_groups g
        LEFT JOIN staging.bridge_equipment__equipment_groups b ON b.eq_group_id = g.eq_group_id
        GROUP BY g.eq_group_id, g.eq_ids
        HAVING expected <> actual"""),
    # eq_group_id is a ROW_NUMBER() recomputed on every run - a new equipment combination shifts the numbering,
    # so groups already loaded into gold must keep their id
    Check("E04", "Group ids are stable against dw.dim_equipment_group", """
        SELECT d.equipment_group_id, d.equipment_group_name, s.eq_group_names
        FROM dw.dim_equipment_group d
        JOIN staging.equipment_groups s ON s.eq_group_id = d.equipment_group_id
        WHERE d.equipment_group_name <> s.eq_group_names"""),
]


@pytest.mark.parametrize("check", as_params(CHECKS))
def test_silver(spark, check):
    run_check(spark, check)
