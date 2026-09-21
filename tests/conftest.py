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
    # si ferma `now_local` e non `datetime`: dal 21 set 2026 l'orologio del
    # gioco e' esplicitamente quello di Roma (util.ROME) e non quello del
    # processo, quindi `weeks` non chiama piu' `datetime.now()`.
    monkeypatch.setattr(weeks, "now_local", lambda: quando)
    return quando


# --- l'app vera, per i test sulle rotte ------------------------------------

PW_TEST = "cacca-segreta"


@pytest.fixture(scope="session")
def web(tmp_path_factory):
    """Il modulo `app.main` avviato su un database usa-e-getta.

    Le rotte si provano solo a livello HTTP: un redirect, un 401 e un toast non
    sono funzioni. `main` legge database e cartella media **all'import**, quindi
    l'ambiente va preparato prima di importarlo — ed e' la ragione per cui vive
    qui dentro e non in cima al file.

    Si salta senza fastapi e httpx (extra `web`), cosi' `uv run --extra dev
    pytest` resta verde."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import os
    d = tmp_path_factory.mktemp("web")
    os.environ["CONQUISTERCO_DB"] = str(d / "test.db")
    os.environ["CONQUISTERCO_MEDIA"] = str(d / "media")
    os.environ["CONQUISTERCO_DEMO"] = "0"
    os.environ["CONQUISTERCO_SECRET"] = "chiave-di-test"
    from conquisterco.app import main
    from conquisterco.app.auth import hash_password
    c = main.connect(main.DB_PATH)
    for nome, ruolo in (("Tizio", "user"), ("Capo", "admin")):
        c.execute("INSERT OR IGNORE INTO users (display_name, password_hash, role)"
                  " VALUES (?,?,?)", (nome, hash_password(PW_TEST), ruolo))
    c.commit()
    c.close()
    return main


@pytest.fixture
def client(web):
    from starlette.testclient import TestClient
    with TestClient(web.app, follow_redirects=False) as c:
        yield c


def entra(client, nome, pw=PW_TEST, next=""):
    return client.post("/login", data={"username": nome, "password": pw, "next": next})
