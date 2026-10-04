from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.safe_export import ROOT, check_payload

DB = ROOT / "db" / "archive.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL,
    game_date TEXT NOT NULL, filename TEXT NOT NULL, build TEXT NOT NULL,
    fmsave_version TEXT NOT NULL, imported_at TEXT NOT NULL,
    club_name TEXT NOT NULL, club_uid INTEGER NOT NULL,
    manager TEXT, validation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    identity_key TEXT PRIMARY KEY, unique_id INTEGER, birth_date TEXT
);
CREATE TABLE IF NOT EXISTS player_snapshots (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    identity_key TEXT NOT NULL REFERENCES players(identity_key),
    visible_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, identity_key)
);
"""


@contextmanager
def connect(db: Path = DB):
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
    finally:
        connection.close()


def import_payload(data: dict, db: Path = DB) -> tuple[int, bool]:
    check_payload(data)
    snap = data["snapshot"]
    with connect(db) as con:
        con.executescript(SCHEMA)
        with con:
            existing = con.execute("SELECT id FROM snapshots WHERE sha256=?", (snap["sha256"],)).fetchone()
            if existing:
                return existing["id"], False
            cursor = con.execute(
                """INSERT INTO snapshots(sha256,game_date,filename,build,fmsave_version,
                   imported_at,club_name,club_uid,manager,validation_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (snap["sha256"], snap["game_date"], snap["filename"], snap["build"],
                 snap["fmsave_version"], datetime.now(timezone.utc).isoformat(),
                 data["club"]["name"], data["club"]["uid"], data["club"]["manager"],
                 json.dumps(data["validation"])),
            )
            sid = cursor.lastrowid
            for player in data["players"]:
                con.execute("INSERT OR IGNORE INTO players VALUES(?,?,?)",
                            (player["identity_key"], player["unique_id"], player["birth_date"]))
                con.execute("INSERT INTO player_snapshots VALUES(?,?,?)",
                            (sid, player["identity_key"], json.dumps(player, ensure_ascii=False)))
        return sid, True


def snapshots(db: Path = DB) -> list[dict]:
    if not db.exists():
        return []
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='snapshots'").fetchone():return []
        return [dict(row) for row in con.execute("SELECT * FROM snapshots ORDER BY game_date DESC,id DESC")]


def squad(snapshot_id: int, db: Path = DB) -> list[dict]:
    with connect(db) as con:
        records = [json.loads(row[0]) for row in con.execute(
            "SELECT visible_json FROM player_snapshots WHERE snapshot_id=?", (snapshot_id,))]
    # Validate before passing any stored content to the UI, too.
    from src.safe_export import PLAYER_FIELDS, ATTRIBUTES, check_keys
    for record in records:
        check_keys(record, PLAYER_FIELDS)
        check_keys(record["attributes"], frozenset(ATTRIBUTES))
    return sorted(records, key=lambda row: (row["name"] or "").casefold())


def history(identity_key: str, db: Path = DB, through_date: str | None = None) -> list[dict]:
    with connect(db) as con:
        rows = con.execute(
            """SELECT s.game_date,p.visible_json FROM player_snapshots p
               JOIN snapshots s ON s.id=p.snapshot_id WHERE identity_key=?
               AND (? IS NULL OR s.game_date<=?) ORDER BY s.game_date,s.id""",
            (identity_key, through_date, through_date)).fetchall()
    # Project the few fields needed, never return arbitrary stored JSON to the UI.
    result = []
    for row in rows:
        player = json.loads(row["visible_json"])
        result.append({"Date": row["game_date"], "Name": player["name"],
                       "Age": player["age"], "Position": " / ".join(player["natural_positions"]),
                       "Contract expiry": player["contract_end"]})
    return result


def import_json(path: Path, db: Path = DB):
    data = json.loads(path.read_text(encoding="utf-8"))
    sid, created = import_payload(data, db)
    print(json.dumps({"snapshot_id": sid, "created": created, "players": len(data["players"])}))
    return sid, created


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    import_json(parser.parse_args().export)
