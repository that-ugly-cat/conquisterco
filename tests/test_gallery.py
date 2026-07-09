from conquisterco.app import data
from conquisterco.ingest import add_deposit, add_user
from conquisterco.pipeline import run_all

from .conftest import CELLS


def test_gallery_progressivo_video_e_meta(conn, geo):
    a = add_user(conn, "A")
    cell = CELLS[1012]   # Roma, quota 21 m nel FakeGeocoder
    add_deposit(conn, user_id=a, ts="2026-01-01 10:00:00",
                lat=cell.lat, lon=cell.lon, source="telegram", photo_ref="a.jpg")
    add_deposit(conn, user_id=a, ts="2026-01-02 10:00:00",
                lat=cell.lat + 0.001, lon=cell.lon, source="telegram", photo_ref="clip.mp4")
    run_all(conn, geo)

    g = data.gallery(conn, a)
    first, second = g["dumps"]     # ordine DESC → il video (2 gen) è primo
    assert first["is_video"] is True and first["n"] == 2
    assert second["is_video"] is False and second["n"] == 1
    # meta nuove nel modale: quota + coordinate per il bottone mappa
    assert first["altitude"] is not None
    assert "lat" in first and "lon" in first
    assert first["comune"] == "Roma"
