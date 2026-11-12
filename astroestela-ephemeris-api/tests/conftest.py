import os
from pathlib import Path

import pytest

TEST_SECRET = "test-secret-" + "x" * 40

# Con archivos reales: EPHEM_DATA_DIR=/ruta pytest. Sin ellos se usa Moshier.
_data = Path(os.environ.get("EPHEM_DATA_DIR", "/nonexistent"))
os.environ.setdefault("EPHEM_HMAC_SECRETS", TEST_SECRET)
if not (_data / "sepl_18.se1").is_file():
    os.environ["EPHEM_ALLOW_MOSHIER"] = "1"
    os.environ["EPHEM_DATA_DIR"] = "/tmp"

REAL_FILES = os.environ.get("EPHEM_ALLOW_MOSHIER") != "1"


@pytest.fixture(scope="session")
def engine():
    from app.engine import Engine

    return Engine(os.environ["EPHEM_DATA_DIR"], allow_moshier=not REAL_FILES)
