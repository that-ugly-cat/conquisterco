from conquisterco.app.auth import hash_password, verify_password
from conquisterco.util import anonymize_name


def test_hash_verify_roundtrip():
    h = hash_password("segreto")
    assert verify_password("segreto", h)
    assert not verify_password("sbagliato", h)
    assert not verify_password("segreto", None)
    assert not verify_password("segreto", "malformato")


def test_hash_ha_salt_casuale():
    assert hash_password("x") != hash_password("x")


def test_anonymize_name():
    assert anonymize_name("Giovanni Spitale") == "Giovanni_S"
    assert anonymize_name("Anna Maria Bertazzo") == "Anna_B"   # iniziale ultimo token
    assert anonymize_name("Madonna") == "Madonna"              # un solo token
