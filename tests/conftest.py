import os
import sys

import pytest

# make project-level modules (e.g. config.py) importable from the tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def pytest_configure(config):
    config.addinivalue_line("markers", "critical: violated check fails the run (severity 'error')")
    config.addinivalue_line("markers", "warning: violated check is only reported (severity 'warning')")


@pytest.fixture(scope="session")
def spark():
    """Spark session: the notebook's session on Databricks, Databricks Connect when run locally."""
    from pyspark.sql import SparkSession

    session = SparkSession.getActiveSession()
    if session is not None:
        return session
    try:
        from databricks.connect import DatabricksSession
        return DatabricksSession.builder.getOrCreate()
    except ImportError:
        return SparkSession.builder.getOrCreate()