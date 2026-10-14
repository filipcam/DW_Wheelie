"""Shared building blocks for the data quality tests.

A check is a SQL query that returns the rows VIOLATING a rule - an empty result means the check passes.
  * severity "error"   -> the pytest test fails (blocks the pipeline)
  * severity "warning" -> the pytest test passes but emits a DataQualityWarning (shown in the pytest summary)
"""
import warnings
from dataclasses import dataclass
from typing import Optional

import pytest

ERROR = "error"
WARNING = "warning"
SAMPLE_ROWS = 5


class DataQualityWarning(UserWarning):
    """Raised for violated checks with severity 'warning'."""


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    sql: str
    severity: str = ERROR
    diagnostic_sql: Optional[str] = None  # extra query whose result is added to the failure message


def unique(check_id, table, cols, where="1=1", severity=ERROR):
    cols_sql = ", ".join(cols)
    name = f"{table}: unique ({cols_sql})" + ("" if where == "1=1" else f" where {where}")
    sql = f"SELECT {cols_sql}, COUNT(*) AS cnt FROM {table} WHERE {where} GROUP BY {cols_sql} HAVING COUNT(*) > 1"
    return Check(check_id, name, sql, severity)


def not_null(check_id, table, cols, severity=ERROR):
    cond = " OR ".join(f"{c} IS NULL" for c in cols)
    return Check(check_id, f"{table}: no NULLs in ({', '.join(cols)})", f"SELECT * FROM {table} WHERE {cond}", severity)


def foreign_key(check_id, child, fk, parent, pk, severity=ERROR):
    sql = f"""SELECT c.* FROM {child} c LEFT JOIN {parent} p ON c.{fk} = p.{pk}
              WHERE c.{fk} IS NOT NULL AND p.{pk} IS NULL"""
    return Check(check_id, f"{child}.{fk} -> {parent}.{pk}", sql, severity)


def as_params(checks):
    """Turns checks into pytest params: readable ids + a 'critical' / 'warning' marker for -m filtering."""
    ids = [c.id for c in checks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"Duplicate check ids: {duplicates}"
    return [
        pytest.param(c, id=f"{c.id} {c.name}", marks=pytest.mark.critical if c.severity == ERROR else pytest.mark.warning)
        for c in checks
    ]


def _format_rows(df, limit):
    rows = df.limit(limit).collect()
    return "\n".join(f"    {r.asDict()}" for r in rows)


def run_check(spark, check: Check):
    violations = spark.sql(check.sql)
    count = violations.count()
    if count == 0:
        return

    message = (f"[{check.id}] {check.name}: {count} violating row(s)\n"
               f"  sample:\n{_format_rows(violations, SAMPLE_ROWS)}\n"
               f"  query:{check.sql}")
    if check.diagnostic_sql:
        message += f"\n  diagnostics:\n{_format_rows(spark.sql(check.diagnostic_sql), 50)}"

    if check.severity == WARNING:
        warnings.warn(message, DataQualityWarning)
    else:
        assert count == 0, message
