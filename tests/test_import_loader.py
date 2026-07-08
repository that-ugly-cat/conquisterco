import io
import zipfile
from pathlib import Path

from conquisterco.db import fresh_db
from conquisterco.importers.loader import import_zip

CHAT = """09/12/23, 20:10 - Alice: ‎IMG-0001.jpg (file allegato)
selfie fiero
09/12/23, 20:11 - Alice: posizione: https://maps.google.com/?q=46.29,11.78
09/12/23, 22:00 - Bob: posizione: https://maps.google.com/?q=45.46,9.19
"""


def _make_zip(path: Path) -> Path:
    zp = path / "Chat WhatsApp con Test.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("Chat WhatsApp con Test.txt", CHAT)
        z.writestr("IMG-0001.jpg", b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return zp


def test_import_filtra_per_allowed(tmp_path):
    zp = _make_zip(tmp_path)
    media = tmp_path / "media"
    conn = fresh_db(":memory:")

    stats = import_zip(conn, zp, media_dir=media, allowed={"Alice"})

    # solo Alice passa il filtro; Bob è scartato
    assert stats["imported"] == 1
    assert stats["skipped_user"] == 1
    names = [r["display_name"] for r in conn.execute("SELECT display_name FROM users")]
    assert names == ["Alice"]

    dep = conn.execute("SELECT lat, lon, source, photo_ref FROM deposits").fetchone()
    assert dep["source"] == "whatsapp_import"
    assert (dep["lat"], dep["lon"]) == (46.29, 11.78)
    # la foto è stata copiata nello store e referenziata
    assert dep["photo_ref"] == "whatsapp/Chat WhatsApp con Test/IMG-0001.jpg"
    assert (media / dep["photo_ref"]).exists()


def test_import_idempotente(tmp_path):
    zp = _make_zip(tmp_path)
    media = tmp_path / "media"
    conn = fresh_db(":memory:")
    import_zip(conn, zp, media_dir=media, allowed={"Alice", "Bob"})
    n1 = conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0]
    # ri-import: la dedup (utente+pin+minuto) evita duplicati
    import_zip(conn, zp, media_dir=media, allowed={"Alice", "Bob"})
    n2 = conn.execute("SELECT COUNT(*) FROM deposits").fetchone()[0]
    assert n1 == n2 == 2
