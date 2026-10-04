"""Future snapshot workflow: immutable backup -> validate -> safe export -> SQLite."""
import argparse
import json
import shutil
import uuid
from pathlib import Path
from src.safe_export import ROOT, file_hash, export_save
from src.archive import import_json


def import_save(source: Path):
    source = source.resolve(strict=True)
    digest = file_hash(source)
    destination = ROOT / "data" / "saves" / f"snapshot_{digest[:16]}.fm"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary=destination.with_suffix('.'+uuid.uuid4().hex+'.part')
        try:
            with source.open("rb") as src, temporary.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            if file_hash(temporary)!=digest or file_hash(source)!=digest:
                raise ValueError('Copy not verified; original may still be saving')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    if file_hash(destination) != digest or file_hash(source) != digest:
        raise ValueError("Copy not verified; original may still be saving")
    exported = export_save(destination)
    result = import_json(exported)
    from src.analytics import import_extended
    import_extended(destination)
    from src.league_archive import export_snapshot
    export_snapshot(destination)
    # Remember only successfully imported source directories for the local update action.
    registry = ROOT / 'data/checks/historical_sources.json'
    registry.parent.mkdir(parents=True, exist_ok=True)
    sources = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else []
    if str(source) not in {row['source'] for row in sources}:
        sources.append({'source': str(source)})
        temporary_registry = registry.with_suffix('.tmp')
        temporary_registry.write_text(json.dumps(sources, indent=2), encoding='utf-8')
        temporary_registry.replace(registry)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("save", type=Path)
    import_save(parser.parse_args().save)
