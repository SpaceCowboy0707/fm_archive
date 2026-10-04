"""One-shot local snapshot update; no model calls or uploads."""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from src.safe_export import ROOT,file_hash
from src.archive import DB,snapshots

def latest_save():
    source_file=ROOT/'data/checks/historical_sources.json'
    if not source_file.exists():raise ValueError('Import a first save with Import-Save.ps1 -SavePath before using automatic update.')
    sources=json.loads(source_file.read_text(encoding='utf-8'))
    folders={Path(r['source']).parent for r in sources}
    candidates=[p for folder in folders for p in folder.glob('last save overwrite backup*.fm')]
    if not candidates:raise ValueError("No automatic backup save found. Specify a path with Import-Save.ps1.")
    return max(candidates,key=lambda p:(p.stat().st_mtime_ns,p.name))

def sync():
    import msvcrt
    lock_path=ROOT/'logs/import.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise ValueError("An import is already running. Please wait.") from None
        try:
            source=latest_save()
            print("Checking whether saving has finished: "+source.name,flush=True)
            before=source.stat()
            time.sleep(3)
            after=source.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError("FM is still writing the save. Update after saving finishes.")
            digest=file_hash(source)
            with sqlite3.connect(DB) as con:
                core=con.execute('SELECT id,game_date FROM snapshots WHERE sha256=?',(digest,)).fetchone()
                extended=con.execute('SELECT 1 FROM analytics_snapshots WHERE sha256=?',(digest,)).fetchone()
                from src.league_archive import has_snapshot
                if core and extended and has_snapshot(digest):
                    print(f'Already up to date: snapshot {core[0]}, game date {core[1]}; no duplicate import.',flush=True)
                    return
                backup=ROOT/'db/backups'/('before-sync-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
                backup.parent.mkdir(exist_ok=True)
                with sqlite3.connect(backup) as target:con.backup(target)
            print("Database backed up. Copying, validating and importing visible data…",flush=True)
            from src.import_save import import_save
            sid,_=import_save(source)
            with sqlite3.connect(DB) as con:
                row=con.execute('SELECT game_date,sha256 FROM snapshots WHERE id=?',(sid,)).fetchone()
                if not con.execute('SELECT 1 FROM analytics_snapshots WHERE sha256=?',(row[1],)).fetchone():
                    raise ValueError("Core snapshot imported but extended statistics are incomplete. Please retry.")
            if not has_snapshot(row[1]):raise ValueError("Premier League snapshot incomplete. Retry; existing snapshots were preserved.")
            print(f'Update complete: snapshot {sid}, game date {row[0]}; now {len(snapshots())} snapshots.',flush=True)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':
    try:sync()
    except Exception as exc:
        print("Update incomplete: "+str(exc),flush=True)
        raise SystemExit(1)
