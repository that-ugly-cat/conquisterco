"""Altitudine dei depositi da DEM (open-meteo elevation API).

Il pin WhatsApp non porta la quota; qui la stimiamo da un modello digitale del
terreno. open-meteo accetta fino a 100 coordinate per richiesta, niente chiave.
`fetch` iniettabile → test senza rete. Sblocca i record più-in-alto/basso e i
badge Scalatore/Batisfera sullo storico.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request

BASE_URL = "https://api.open-meteo.com"
_UA = "conquisterco/0.1 (il Cacasto)"


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_elevations(points: list[tuple[float, float]], *, fetch=None,
                     base_url: str = BASE_URL, batch: int = 100) -> list[float | None]:
    """Quota (m) per una lista di (lat, lon). None dove ignota. Ordine preservato."""
    fetch = fetch or _default_fetch
    out: list[float | None] = []
    for i in range(0, len(points), batch):
        chunk = points[i:i + batch]
        lats = ",".join(str(p[0]) for p in chunk)
        lons = ",".join(str(p[1]) for p in chunk)
        try:
            data = json.loads(fetch(f"{base_url}/v1/elevation?latitude={lats}&longitude={lons}"))
            els = data.get("elevation") or []
        except Exception:
            els = []
        out.extend(els[j] if j < len(els) else None for j in range(len(chunk)))
    return out


def enrich_altitude(conn: sqlite3.Connection, *, fetcher=fetch_elevations) -> dict:
    """Riempie l'altitudine dei depositi che non ce l'hanno. Ritorna un riepilogo."""
    rows = conn.execute("SELECT id, lat, lon FROM deposits WHERE altitude IS NULL").fetchall()
    if not rows:
        return {"pending": 0, "updated": 0}
    els = fetcher([(r["lat"], r["lon"]) for r in rows])
    n = 0
    for r, e in zip(rows, els):
        if e is not None:
            conn.execute("UPDATE deposits SET altitude=?, alt_source='dem' WHERE id=?", (e, r["id"]))
            n += 1
    conn.commit()
    return {"pending": len(rows), "updated": n}
