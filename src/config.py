"""Settings for the DHIS2 reporting check. Override any of them in a .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"     # offline sample API responses (synthetic)
RAW_DIR = DATA_DIR / "raw"           # live API responses are saved here (not committed)
OUTPUT_DIR = ROOT / "outputs"
IMAGE_DIR = ROOT / "docs" / "images"


def _env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_env()

# Connection. The public demo resets every night and is shared by everyone.
# Demo addresses change with each DHIS2 release: open https://play.dhis2.org, pick an
# instance and put its address (https://play.im.dhis2.org/...) in DHIS2_URL in .env.
DHIS2_URL = os.environ.get("DHIS2_URL", "https://play.dhis2.org/demo")
DHIS2_USER = os.environ.get("DHIS2_USER", "admin")
DHIS2_PASS = os.environ.get("DHIS2_PASS", "district")

# What to analyse
DATASET_NAME = os.environ.get("DHIS2_DATASET", "Child Health")            # monthly facility report
DATA_ELEMENT_NAME = os.environ.get("DHIS2_DATA_ELEMENT", "ANC 1st visit")  # value to scan for outliers
FACILITY_LEVEL = int(os.environ.get("DHIS2_FACILITY_LEVEL", "4"))         # level of health facilities
PERIOD = os.environ.get("DHIS2_PERIOD", "LAST_12_MONTHS")

# Thresholds
COMPLETENESS_TARGET = 0.80     # facilities should submit at least 80% of expected reports
TIMELINESS_TARGET = 0.80       # and at least 80% on time
SILENT_MONTHS = 3              # this many missing reports in a row = facility has gone silent
OUTLIER_Z = 3.5                # modified z-score above this = outlier (Iglewicz and Hoaglin rule)
