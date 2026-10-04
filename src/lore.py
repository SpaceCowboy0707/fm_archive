"""Manual stories remain outside snapshot imports and keep explicit evidence levels."""
import json
from pathlib import Path
from src.safe_export import ROOT, check_keys

LORE = ROOT / "data" / "manual" / "lore.json"
IMPORTED_LORE = ROOT / "data" / "conversations" / "story-excerpts.json"
LEVELS = {"canon": "Game fact", "inferred": "Inference", "headcanon": "Headcanon"}
FIELDS = frozenset({"id", "level", "title", "text", "source", "season", "player_keys", "player_names"})


def load_lore(path: Path = LORE) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else dict(schema_version=1,entries=[])
    if path == LORE:
        from src.chat_store import collected_lore
        document['entries'] = [*document['entries'], *collected_lore()]
    if path == LORE and IMPORTED_LORE.exists():
        imported = json.loads(IMPORTED_LORE.read_text(encoding="utf-8"))
        check_keys(imported, frozenset({"schema_version", "entries"}))
        if imported['schema_version'] != 1:
            raise ValueError('Unsupported imported lore schema')
        document['entries'] = [*document['entries'], *imported['entries']]
    check_keys(document, frozenset({"schema_version", "entries"}))
    if document["schema_version"] != 1:
        raise ValueError("Unsupported lore schema")
    seen = set()
    for entry in document["entries"]:
        check_keys(entry, FIELDS)
        if entry["level"] not in LEVELS:
            raise ValueError("Lore must be canon, inferred, or headcanon")
        for key in ("id", "title", "text", "source"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise ValueError("Lore needs an ID, title, text and source")
        if entry["id"] in seen:
            raise ValueError("Duplicate lore ID")
        if not isinstance(entry["player_keys"], list) or not isinstance(entry["player_names"], list):
            raise ValueError("Lore player references must be lists")
        seen.add(entry["id"])
    return document["entries"]
