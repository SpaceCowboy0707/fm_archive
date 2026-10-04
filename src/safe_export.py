"""Explicit projection only. Never serialize a fmsave player or nested record."""
from __future__ import annotations

from src.i18n import INPUT_ALIASES
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTES = tuple("""crossing dribbling finishing heading long_shots marking
off_the_ball passing penalty_taking tackling vision handling aerial_reach
command_of_area communication kicking throwing anticipation decisions one_on_ones
positioning reflexes first_touch technique flair corners teamwork work_rate
long_throws eccentricity rushing_out punching acceleration free_kick_taking
strength stamina pace jumping_reach leadership balance bravery aggression agility
natural_fitness determination composure concentration""".split())
PLAYER_FIELDS = frozenset("""identity_key uid unique_id name birth_date age nation_id
height_cm club_uid club_name team_slot natural_positions club_join_date
contract_end squad_status on_loan loan_parent_club_name attributes""".split())
TOP_FIELDS = frozenset({"schema_version", "snapshot", "club", "players", "validation"})
SNAPSHOT_FIELDS = frozenset({"sha256", "filename", "game_date", "build", "fmsave_version", "exported_at"})
CLUB_FIELDS = frozenset({"uid", "name", "manager"})
VALIDATION_FIELDS = frozenset({"reader", "status", "record_count"})


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def iso(value):
    return value.isoformat() if value is not None else None


def identity(player) -> str:
    kind = "game" if player.unique_id is not None else "parser"
    number = player.unique_id if player.unique_id is not None else player.uid
    return f"{kind}:{number}:{iso(player.birth_date) or 'unknown'}"


def project_player(player) -> dict:
    contract = player.contract
    # Deliberately access named visible fields only, including each attribute.
    return {
        "identity_key": identity(player), "uid": player.uid,
        "unique_id": player.unique_id, "name": player.name,
        "birth_date": iso(player.birth_date), "age": player.age,
        "nation_id": player.nation_id, "height_cm": player.height_cm,
        "club_uid": player.club_uid, "club_name": player.club_name,
        "team_slot": player.team_slot,
        "natural_positions": list(player.natural_positions),
        "club_join_date": iso(player.club_join_date),
        "contract_end": iso(contract.end) if contract else None,
        "squad_status": contract.squad_status.label_text if contract and contract.squad_status else None,
        "on_loan": player.on_loan,
        "loan_parent_club_name": player.loan_parent_club_name,
        "attributes": {key: getattr(player.attributes, key) for key in ATTRIBUTES},
    }


def check_keys(record, allowed):
    if not isinstance(record, dict) or set(record) != allowed:
        raise ValueError("Schema rejected: unexpected or missing fields; values suppressed")


def check_payload(data: dict):
    check_keys(data, TOP_FIELDS)
    if data["schema_version"] != 1:
        raise ValueError("Unsupported schema version")
    check_keys(data["snapshot"], SNAPSHOT_FIELDS)
    check_keys(data["club"], CLUB_FIELDS)
    seen = set()
    for record in data["validation"]:
        check_keys(record, VALIDATION_FIELDS)
    if not data["players"]:
        raise ValueError("Empty squad; import stopped")
    for record in data["players"]:
        check_keys(record, PLAYER_FIELDS)
        check_keys(record["attributes"], frozenset(ATTRIBUTES))
        if record["club_uid"] != data["club"]["uid"]:
            raise ValueError("Player outside managed club")
        if record["identity_key"] in seen:
            raise ValueError("Duplicate identity; import stopped")
        seen.add(record["identity_key"])
        for value in record["attributes"].values():
            if type(value) is not int or not 1 <= value <= 20:
                raise ValueError("Visible attribute outside 1-20; import stopped")


def export_save(save_path: Path, *, verified_report: Path | None = None) -> Path:
    import fmsave
    from importlib.metadata import version
    digest = file_hash(save_path)
    with fmsave.open(save_path, strict=True) as career:
        if verified_report:
            report = json.loads(verified_report.read_text(encoding="utf-8-sig"))
            receipt = json.loads(verified_report.with_suffix(".receipt.json").read_text(encoding="utf-8-sig"))
            if receipt["sha256"] != digest or report["fmsave_version"] != version("fmsave"):
                raise ValueError("Validation receipt mismatch")
            checks = [{key: row[key] for key in VALIDATION_FIELDS} for row in report["readers"]]
        else:
            report = fmsave.validate_save(career)
            checks = [{"reader": row.reader, "status": str(row.status), "record_count": row.record_count}
                      for row in report.readers]
        statuses = {row["reader"]: row["status"] for row in checks}
        if any(statuses.get(name) != "ok" for name in ("clubs", "managed_clubs", "players", "contracts")):
            raise ValueError("A required reader failed validation; no export written")
        clubs = career.managed_clubs()
        if len(clubs) != 1:
            raise ValueError("Exactly one managed club is required")
        club = clubs[0]
        if not any(label in club.club_name.casefold() for label in INPUT_ALIASES['club_aliases']):
            raise ValueError("Managed club is not Leicester; no export written")
        payload = {
            "schema_version": 1,
            "snapshot": {"sha256": digest, "filename": save_path.name,
                         "game_date": iso(career.info.game_date), "build": career.info.build,
                         "fmsave_version": version("fmsave"),
                         "exported_at": datetime.now(timezone.utc).isoformat()},
            "club": {"uid": club.club_uid, "name": club.club_name, "manager": club.manager_name},
            "players": [project_player(player) for player in career.players().where(club_uid=club.club_uid)],
            "validation": checks,
        }
    if file_hash(save_path) != digest:
        raise ValueError("Save changed during export")
    check_payload(payload)
    destination = ROOT / "data" / "raw" / f"{payload['snapshot']['game_date']}_{digest[:12]}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    print(json.dumps({"export": str(destination), "club": payload["club"],
                      "game_date": payload["snapshot"]["game_date"],
                      "players": len(payload["players"])}))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("save", type=Path)
    parser.add_argument("--verified-report", type=Path)
    args = parser.parse_args()
    export_save(args.save, verified_report=args.verified_report)
