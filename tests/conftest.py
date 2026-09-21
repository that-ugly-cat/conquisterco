import sqlite3
from datetime import datetime
from types import SimpleNamespace

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


@pytest.fixture
def domenica(monkeypatch):
    """Ferma l'orologio di `weeks` a una domenica sera, come il recap vero, e
    ritorna quell'istante.

    Serve perche' senza, i test che chiudono una settimana **dipendono dal
    giorno in cui si lanciano**: `MIN_WEEK_DAYS` impedisce di chiudere una
    settimana appena cominciata, quindi da lunedi' a mercoledi'
    `close_due_weeks(closing_now=True)` ritorna una lista vuota e tredici test
    cadono in fila. Scoperto il 21 settembre 2026, un lunedi' mattina, su test
    scritti il venerdi' e verdi per tre giorni.

    Chi usa questa fixture deve datare i propri depositi rispetto all'istante
    che ritorna, non a `datetime.now()`."""
    quando = datetime(2026, 9, 20, 20, 0, 0)     # domenica, ora del cron
    from conquisterco import weeks
    monkeypatch.setattr(weeks, "datetime", SimpleNamespace(now=lambda: quando))
    return quando
