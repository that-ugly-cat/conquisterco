"""Replay dei flip nel tempo: ricostruisce l'ownership istante per istante.

Serve alle logiche che dipendono dallo stato simultaneo o dalla storia:
  - Conquistador  (rubare un comune a un altro utente)
  - Regicidio     (rubarlo a chi è in testa alla classifica)
  - Guardiano     (riprendersi un comune dopo un pareggio subìto)
  - Latifondista  (record di comuni posseduti in contemporanea)
  - Spartizione della Polonia (>=N comuni polacchi insieme)

Un solo replay, consumato sia dall'evaluator degli achievement sia dalle
leaderboard, così la semantica di gioco vive in un posto solo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Conquest:
    ts: str
    territory: int
    new_owner: int
    displaced: int          # ultimo owner reale spodestato
    leader_before: int | None  # chi era in testa (comuni posseduti) prima del flip


@dataclass
class Guard:
    ts: str
    territory: int
    user: int


@dataclass
class ReplayResult:
    conquests: list[Conquest] = field(default_factory=list)
    guards: list[Guard] = field(default_factory=list)
    max_owned: dict[int, int] = field(default_factory=dict)          # user -> max comuni insieme
    max_owned_by_country: dict[str, dict[int, int]] = field(default_factory=dict)  # country -> user -> max


def _leader(owner_by_t: dict[int, int]) -> int | None:
    """Utente con più comuni posseduti, in modo stretto. None se parità/vuoto."""
    if not owner_by_t:
        return None
    tally = Counter(owner_by_t.values())
    top = max(tally.values())
    leaders = [u for u, c in tally.items() if c == top]
    return leaders[0] if len(leaders) == 1 else None


def replay_flips(flips: list[dict], territory_country: dict[int, str | None],
                 *, track_countries: tuple[str, ...] = ()) -> ReplayResult:
    """`flips`: dict con ts, territory, prev_owner, new_owner — ordinati per (ts, id).
    `territory_country`: osm_id -> nazione. `track_countries`: nazioni per cui
    tracciare il record di possesso simultaneo (es. Polonia)."""
    res = ReplayResult()
    res.max_owned = {}
    for c in track_countries:
        res.max_owned_by_country[c] = {}

    owner_by_t: dict[int, int] = {}
    last_real_owner: dict[int, int] = {}
    prev_flip: dict[int, dict] = {}

    def bump(d: dict[int, int], user: int, value: int) -> None:
        if value > d.get(user, 0):
            d[user] = value

    for f in flips:
        t = f["territory"]
        newo = f["new_owner"]

        leader_before = _leader(owner_by_t)

        # Conquista: prendi un comune il cui ultimo owner reale era un altro.
        lro = last_real_owner.get(t)
        if newo is not None and lro is not None and lro != newo:
            res.conquests.append(Conquest(
                ts=f["ts"], territory=t, new_owner=newo,
                displaced=lro, leader_before=leader_before,
            ))

        # Guardiano: il flip precedente ti aveva tolto il comune (owner U -> conteso)
        # e ora te lo riprendi (conteso -> U).
        pf = prev_flip.get(t)
        if (pf is not None and newo is not None
                and pf["new_owner"] is None and pf["prev_owner"] == newo):
            res.guards.append(Guard(ts=f["ts"], territory=t, user=newo))

        # applica il flip
        if newo is None:
            owner_by_t.pop(t, None)
        else:
            owner_by_t[t] = newo
            last_real_owner[t] = newo
        prev_flip[t] = f

        # aggiorna i record di possesso simultaneo
        totals = Counter(owner_by_t.values())
        for u, c in totals.items():
            bump(res.max_owned, u, c)
        for country in track_countries:
            sub = Counter(
                u for tt, u in owner_by_t.items()
                if territory_country.get(tt) == country
            )
            for u, c in sub.items():
                bump(res.max_owned_by_country[country], u, c)

    return res
