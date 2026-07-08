from conquisterco.importers.whatsapp import detect_dumps, parse_chat, roster

# Fixture sintetica che imita il formato reale (nessun dato personale).
CHAT = """08/12/23, 21:52 - Sistema: I messaggi sono crittografati
08/12/23, 21:52 - Riga di sistema senza colon dopo il trattino
09/12/23, 20:10 - Alice: ‎IMG-0001.jpg (file allegato)
didascalia su riga a parte
09/12/23, 20:12 - Alice: posizione: https://maps.google.com/?q=46.29,11.78
09/12/23, 22:00 - Bob: posizione: https://maps.google.com/?q=45.46,9.19
10/12/23, 09:00 - Bob: ‎IMG-0002.jpg (file allegato)
"""


def test_parse_messaggi_e_continuazione():
    msgs = parse_chat(CHAT)
    # la riga di sistema senza "Nome:" non crea un messaggio (né lo spezza)
    senders = [m.sender for m in msgs]
    assert "Alice" in senders and "Bob" in senders
    alice_media = next(m for m in msgs if m.sender == "Alice" and m.media)
    assert alice_media.media == "IMG-0001.jpg"
    assert "didascalia" in alice_media.body  # continuazione agganciata


def test_estrazione_coords():
    msgs = parse_chat(CHAT)
    pin = next(m for m in msgs if m.coords)
    assert pin.coords == (46.29, 11.78)


def test_detect_dumps_pin_e_foto():
    dumps = detect_dumps(parse_chat(CHAT), window_min=5)
    assert len(dumps) == 2  # ogni pin è un dump
    alice = next(d for d in dumps if d.sender == "Alice")
    bob = next(d for d in dumps if d.sender == "Bob")
    assert alice.photo == "IMG-0001.jpg"   # foto entro 2 min
    assert bob.photo is None               # foto a >5 min → coniglio


def test_finestra_stretta_scarta_foto():
    dumps = detect_dumps(parse_chat(CHAT), window_min=1)
    alice = next(d for d in dumps if d.sender == "Alice")
    assert alice.photo is None  # 2 min > finestra di 1 min


def test_roster():
    r = roster(parse_chat(CHAT))
    assert r["Alice"] == 2 and r["Bob"] == 2
