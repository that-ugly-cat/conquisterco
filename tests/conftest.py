import sqlite3

import pytest

from conquisterco.db import fresh_db
from conquisterco.geo import FakeGeocoder
from conquisterco.ingest import add_user

# centri dei comuni fittizi, per piazzare depositi deterministici
CELLS = {c.osm_id: c for c in FakeGeocoder().cells}


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = fresh_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def geo() -> FakeGeocoder:
    return FakeGeocoder()


def dep(conn, uid, osm_id, ts, *, photo=True):
    """Helper: deposita al centro del comune `osm_id` a un dato timestamp."""
    from conquisterco.ingest import add_deposit
    cell = CELLS[osm_id]
    return add_deposit(
        conn, user_id=uid, ts=ts,
        lat=cell.lat + 0.001, lon=cell.lon + 0.001,
        source="telegram", photo_ref="x.jpg" if photo else None,
    )


def mkuser(conn, name, **kw):
    return add_user(conn, name, **kw)
