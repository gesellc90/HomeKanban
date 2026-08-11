from __future__ import annotations

from pathlib import Path

import pytest

from app.db import connect, transaction


def test_connect_applies_expected_pragmas(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    try:
        connection.execute("CREATE TABLE t (id INTEGER)")
        with transaction(connection):
            connection.execute("INSERT INTO t VALUES (1)")

        assert connection.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    finally:
        connection.close()


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    connection = connect(tmp_path / "test.db")
    try:
        connection.execute("CREATE TABLE t (id INTEGER)")

        with pytest.raises(RuntimeError), transaction(connection):
            connection.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")

        assert connection.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    finally:
        connection.close()
