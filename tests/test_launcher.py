"""Launcher helpers. These need no web server."""
import datetime as dt
import os
import socket
import sqlite3
import tempfile
from pathlib import Path

import orderdesk


def tmp():
    return Path(tempfile.mkdtemp())


def test_data_dir_override_is_created():
    d = tmp() / "deep" / "folder"
    old = os.environ.get("ORDERDESK_DATA")
    os.environ["ORDERDESK_DATA"] = str(d)
    try:
        assert orderdesk.data_dir() == d and d.is_dir()
    finally:
        if old is None:
            os.environ.pop("ORDERDESK_DATA", None)
        else:
            os.environ["ORDERDESK_DATA"] = old


def test_lan_ip_is_an_address_or_none():
    ip = orderdesk.lan_ip()
    assert ip is None or (socket.inet_aton(ip) and not ip.startswith("127."))


def test_port_checks():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        assert orderdesk.port_is_free(busy) is False
        assert orderdesk.already_running(busy) is False      # something is listening, but it is not our server
    finally:
        s.close()


def make_db(path):
    c = sqlite3.connect(path)
    c.execute("create table t (v text)")
    c.execute("insert into t values ('hello')")
    c.commit()
    c.close()


def test_backup_copies_data_once_a_day_and_keeps_30():
    d = tmp()
    db = d / "orders.db"
    make_db(db)
    dest = d / "backups"
    first = orderdesk.backup_db(db, dest, today=dt.date(2026, 10, 1))
    assert first and sqlite3.connect(first).execute("select v from t").fetchone()[0] == "hello"
    assert orderdesk.backup_db(db, dest, today=dt.date(2026, 10, 1)) is None     # same day: skipped
    for n in range(2, 41):
        orderdesk.backup_db(db, dest, today=dt.date(2026, 10, 1) + dt.timedelta(days=n))
    names = sorted(p.name for p in dest.glob("orders-*.db"))
    assert len(names) == 30 and names[-1] == "orders-20261110.db" and "orders-20261001.db" not in names
    assert not list(dest.glob("*.tmp"))
    assert orderdesk.backup_db(d / "missing.db", dest) is None
