import os
import subprocess
import sys
import sqlite3
from pathlib import Path


def test_migrations_upgrade_downgrade_upgrade(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration-test.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}"}
    commands = (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "alembic", "downgrade", "c1a8e2f4b6d0"],
        [sys.executable, "-m", "alembic", "upgrade", "head"],
    )
    for command in commands:
        subprocess.run(command, cwd=root, env=env, check=True, capture_output=True, text=True)
    with sqlite3.connect(database) as connection:
        unique_columns = []
        for index in connection.execute("PRAGMA index_list(po_line)").fetchall():
            if index[2]:
                unique_columns.append([row[2] for row in connection.execute(
                    'PRAGMA index_info("' + index[1].replace('"', '""') + '")').fetchall()])
        assert ["result_id"] not in unique_columns
        assert ["result_id", "draft_id"] in unique_columns
