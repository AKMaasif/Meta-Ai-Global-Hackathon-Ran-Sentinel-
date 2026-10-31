import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings  # noqa: E402
from app.orchestrator import Sentinel  # noqa: E402
from app.providers import OfflineProvider  # noqa: E402
from app.store import Store  # noqa: E402


def offline_settings() -> Settings:
    s = Settings()
    s.api_key = ""
    s.maveric_url = ""
    return s


@pytest.fixture
def sentinel():
    sen = Sentinel(offline_settings(), Store(":memory:"), OfflineProvider())
    sen.sync = True
    return sen


def run_until(sen, cid, ticks=4):
    for _ in range(ticks):
        sen.tick()
        if cid in sen.open_by_cell:
            break
    iid = sen.open_by_cell.get(cid)
    return sen.incidents.get(iid) if iid else None
