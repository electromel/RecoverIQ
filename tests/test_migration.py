"""Migration des données depuis l'ancien dossier (%LOCALAPPDATA%\\RecoverIQ)."""

import sqlite3

from recoveriq.db.legacy_migration import migrate_legacy_home


def _make_old_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    return conn  # laissée ouverte : les données restent dans le journal WAL


def test_copies_db_with_wal_and_tokens(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    keep_open = _make_old_db(old / "recoveriq.db")
    (old / "garmin_tokens.bin").write_bytes(b"secret")
    try:
        assert migrate_legacy_home(old, new) is True
    finally:
        keep_open.close()
    copied = sqlite3.connect(new / "recoveriq.db")
    assert copied.execute("SELECT v FROM t").fetchone() == (42,)
    copied.close()
    assert (new / "garmin_tokens.bin").read_bytes() == b"secret"
    assert (old / "recoveriq.db").exists()            # ancien dossier intact


def test_noop_when_new_db_exists_or_old_missing(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    assert migrate_legacy_home(old, new) is False      # pas d'ancienne base
    old.mkdir()
    _make_old_db(old / "recoveriq.db").close()
    new.mkdir()
    (new / "recoveriq.db").write_bytes(b"")
    assert migrate_legacy_home(old, new) is False      # ne jamais écraser
    assert migrate_legacy_home(None, new) is False
