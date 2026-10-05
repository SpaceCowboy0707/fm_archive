"""Team-scoped Premier League snapshots. No contracts, injuries or hidden attributes."""
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.archive import DB
from src.safe_export import ROOT, ATTRIBUTES, file_hash, iso, check_keys
from src.analytics import SEASON_FIELDS, project, COUNTS

COMPETITION_DB_ID=11  # Confirmed against this career's 20-club Leicester division and fixtures.
KINDS=('league','cup','continental','overall','non_competitive')
ROSTER_FIELDS=('uid','name','birth_date','age','height_cm','natural_positions','attributes')
STANDING_FIELDS=('position','team_id','club_uid','club_name','played','won','drawn','lost','goals_for','goals_against','points')
SCHEMA="""
CREATE TABLE IF NOT EXISTS league_snapshots(
 sha256 TEXT PRIMARY KEY,game_date TEXT NOT NULL,season TEXT NOT NULL,
 competition_db_id INTEGER NOT NULL,league_complete INTEGER NOT NULL,
 reset_detected INTEGER NOT NULL,note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS league_teams(
 club_uid INTEGER PRIMARY KEY,club_unique_id INTEGER,club_name TEXT NOT NULL,first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS league_team_snapshots(
 sha256 TEXT NOT NULL REFERENCES league_snapshots(sha256),club_uid INTEGER NOT NULL,
 club_name TEXT NOT NULL,team_id INTEGER NOT NULL,in_premier INTEGER NOT NULL,
 roster_json TEXT NOT NULL,stats_json TEXT NOT NULL,standing_json TEXT,
 coverage_json TEXT NOT NULL,PRIMARY KEY(sha256,club_uid));
CREATE TABLE IF NOT EXISTS league_frozen_seasons(
 season TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,as_of TEXT NOT NULL,
 league_complete INTEGER NOT NULL,frozen_at TEXT NOT NULL,note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS league_offseason_skips(
 sha256 TEXT PRIMARY KEY,game_date TEXT NOT NULL,finished_season TEXT NOT NULL,
 next_season TEXT NOT NULL,next_start TEXT NOT NULL,note TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS v_league_team_current AS
 SELECT t.*,s.game_date,s.season,s.league_complete FROM league_team_snapshots t
 JOIN league_snapshots s ON s.sha256=t.sha256
 WHERE s.sha256=(SELECT sha256 FROM league_snapshots ORDER BY game_date DESC,sha256 DESC LIMIT 1);
CREATE VIEW IF NOT EXISTS v_league_team_season AS
 SELECT t.*,s.game_date,s.season,s.league_complete,
 CASE WHEN f.season IS NULL THEN 'live' ELSE 'frozen' END AS archive_status
 FROM league_team_snapshots t JOIN league_snapshots s ON s.sha256=t.sha256
 LEFT JOIN league_frozen_seasons f ON f.season=s.season
 WHERE s.sha256=COALESCE(f.source_sha256,(SELECT s2.sha256 FROM league_snapshots s2
 WHERE s2.season=s.season ORDER BY game_date DESC,sha256 DESC LIMIT 1));
CREATE VIEW IF NOT EXISTS v_league_player_stats AS
 SELECT t.sha256,t.club_uid,t.club_name,t.in_premier,t.season,t.game_date,t.archive_status,
 json_extract(j.value,'$.player_uid') AS player_uid,
 json_extract(j.value,'$.player_name') AS player_name,
 json_extract(j.value,'$.kind') AS kind,
 json_extract(j.value,'$.minutes') AS minutes,
 json_extract(j.value,'$.goals') AS goals,
 json_extract(j.value,'$.assists') AS assists,
 json_extract(j.value,'$.average_rating') AS average_rating,
 j.value AS detail_json
 FROM v_league_team_season t,json_each(t.stats_json) j;
"""


def connection(db=DB):
    con=sqlite3.connect(db,timeout=30)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def initialize(db=DB):
    with closing(connection(db)) as con:
        con.executescript(SCHEMA)
        con.commit()


def has_snapshot(digest,db=DB):
    with closing(connection(db)) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone()
        return bool(exists and con.execute('SELECT 1 FROM league_snapshots WHERE sha256=?',(digest,)).fetchone())


def offseason_skip(digest,db=DB):
    with closing(connection(db)) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='league_offseason_skips'").fetchone()
        row=exists and con.execute('SELECT * FROM league_offseason_skips WHERE sha256=?',(digest,)).fetchone()
        return dict(row) if row else None


def current_season(day,db=DB):
    """Season of the latest league snapshot on or before day. Between seasons this stays on the
    finished season, which has the data; None when no league snapshot exists."""
    if not Path(db).exists():return None
    with closing(connection(db)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone():return None
        row=con.execute('SELECT season FROM league_snapshots WHERE game_date<=? ORDER BY game_date DESC,sha256 DESC LIMIT 1',(day,)).fetchone()
        return row['season'] if row else None


def stage_done(digest,db=DB):
    """A save is finished for the league stage when it was stored or recorded as an off-season skip."""
    return has_snapshot(digest,db) or offseason_skip(digest,db) is not None


def squad_projection(p):
    return dict(uid=p.uid,name=p.name,birth_date=iso(p.birth_date),age=p.age,height_cm=p.height_cm,
                natural_positions=list(p.natural_positions),attributes={k:getattr(p.attributes,k) for k in ATTRIBUTES})


def infer_season(table,fixtures,day):
    teams={r.team_id for r in table.rows}
    groups=defaultdict(dict)
    for f in fixtures:
        if (f.competition_id==table.competition_id and f.season_start_year is not None
            and f.home_team_id in teams and f.away_team_id in teams):
            groups[f.season_start_year][(f.home_team_id,f.away_team_id)]=f
    played=sum(r.played for r in table.rows)
    candidates=[]
    for year,pairs in groups.items():
        if len(pairs)!=380:continue
        count=sum(bool(f.played and f.date and f.date<=day) for f in pairs.values())
        if count*2==played:candidates.append(year)
    if len(candidates)!=1:
        raise ValueError("The Premier League season could not be uniquely reconciled using the 380 fixtures and table appearances. Nothing was written.")
    year=candidates[0]
    return f'{year}/{str(year+1)[-2:]}'


def offseason(comps,fixtures,day):
    """FM drops the Premier League table between seasons. Recognise only the clear case: last season's
    380 fixtures are all played and the next 380 are scheduled but none has started."""
    ids={cid for cid,db_id in comps.items() if db_id==COMPETITION_DB_ID}
    groups=defaultdict(dict)
    for f in fixtures:
        if f.competition_id in ids and f.season_start_year is not None:
            groups[f.season_start_year][(f.home_team_id,f.away_team_id)]=f
    if not groups:return None
    year=max(groups)
    upcoming,finished=groups[year].values(),groups.get(year-1,{}).values()
    if len(upcoming)!=380 or len(finished)!=380:return None
    if any(f.played or not f.date or f.date<=day for f in upcoming):return None
    if not all(f.played and f.date and f.date<=day for f in finished):return None
    return dict(finished_season=f'{year-1}/{str(year)[-2:]}',next_season=f'{year}/{str(year+1)[-2:]}',
                next_start=iso(min(f.date for f in upcoming)))


def detect_reset(previous,teams):
    """Only declare rollover when a finished league's cumulative counters collapse broadly."""
    if not previous:return False
    old={t['club_uid']:sum(r['minutes'] or 0 for r in t['stats'] if r['kind']=='league') for t in previous}
    eligible=[t for t in teams if old.get(t['club_uid'],0)>1000]
    drops=sum(sum(r['minutes'] or 0 for r in t['stats'] if r['kind']=='league')<old[t['club_uid']]*0.5 for t in eligible)
    return len(eligible)>=15 and drops>=len(eligible)*0.75


def validate_payload(payload):
    check_keys(payload,{'sha256','game_date','season','competition_db_id','league_complete','reset_detected','note','teams'})
    if payload['competition_db_id']!=COMPETITION_DB_ID:raise ValueError('Wrong competition')
    if len([t for t in payload['teams'] if t['in_premier']])!=20:raise ValueError('Expected 20 Premier League teams')
    if len({t['club_uid'] for t in payload['teams']})!=len(payload['teams']):raise ValueError('Duplicate club')
    for t in payload['teams']:
        check_keys(t,{'club_uid','club_unique_id','club_name','team_id','in_premier','roster','stats','standing','coverage'})
        for p in t['roster']:
            check_keys(p,set(ROSTER_FIELDS));check_keys(p['attributes'],set(ATTRIBUTES))
        for row in t['stats']:
            check_keys(row,set(SEASON_FIELDS))
            if row['team_id']!=t['team_id'] or row['club_uid']!=t['club_uid'] or row['team_slot']!=0 or row['kind'] not in KINDS:
                raise ValueError('Team attribution mismatch')
        if t['standing'] is not None:check_keys(t['standing'],set(STANDING_FIELDS))
        check_keys(t['coverage'],{'roster_count','stats_by_kind','league_player_count','league_stat_null_counts','note'})
        check_keys(t['coverage']['league_stat_null_counts'],set(COUNTS))
        if not set(t['coverage']['stats_by_kind']).issubset(KINDS):raise ValueError('Invalid stats kind')


def freeze_previous(con,current_season):
    # Freeze a complete team snapshot, never mix players or team rows from different days.
    periods=[r[0] for r in con.execute('SELECT DISTINCT season FROM league_snapshots WHERE season<?',(current_season,))]
    for period in periods:
        if con.execute('SELECT 1 FROM league_frozen_seasons WHERE season=?',(period,)).fetchone():continue
        last=con.execute('SELECT * FROM league_snapshots WHERE season=? ORDER BY game_date DESC,sha256 DESC LIMIT 1',(period,)).fetchone()
        if last:
            note="Last valid whole-team snapshot of the previous season. All 38 league matches are complete; cups may not be finished." if last['league_complete'] else "Last valid snapshot of the previous season. No complete end-of-season save exists; this is a partial season."
            con.execute('INSERT INTO league_frozen_seasons VALUES(?,?,?,?,?,?)',(period,last['sha256'],last['game_date'],last['league_complete'],datetime.now(timezone.utc).isoformat(),note))


def store(payload,db=DB):
    validate_payload(payload)
    initialize(db)
    with closing(connection(db)) as con,con:
        if con.execute('SELECT 1 FROM league_snapshots WHERE sha256=?',(payload['sha256'],)).fetchone():return False
        con.execute('INSERT INTO league_snapshots VALUES(?,?,?,?,?,?,?)',tuple(payload[k] for k in ('sha256','game_date','season','competition_db_id','league_complete','reset_detected','note')))
        for t in payload['teams']:
            con.execute('INSERT INTO league_teams VALUES(?,?,?,?) ON CONFLICT(club_uid) DO UPDATE SET first_seen=MIN(first_seen,excluded.first_seen)',
                        (t['club_uid'],t['club_unique_id'],t['club_name'],payload['game_date']))
            con.execute('INSERT INTO league_team_snapshots VALUES(?,?,?,?,?,?,?,?,?)',
                (payload['sha256'],t['club_uid'],t['club_name'],t['team_id'],t['in_premier'],
                 json.dumps(t['roster'],ensure_ascii=False),json.dumps(t['stats'],ensure_ascii=False),
                 json.dumps(t['standing'],ensure_ascii=False),json.dumps(t['coverage'],ensure_ascii=False)))
        current=con.execute('SELECT MAX(season) FROM league_snapshots').fetchone()[0]
        freeze_previous(con,current)
    return True


def only_division_gate(exc):
    """Late in the off-season most leagues have reset, so fmsave's strict count of double round-robin
    divisions falls below its floor. That alone is expected then; any other failed check is not."""
    failed=[(c.reader,g.name) for c in exc.checks for g in c.gates if not g.passed]
    return bool(failed) and all(f==('league_tables','double_round_robin_divisions') for f in failed)


def record_offseason(path,digest,day,gap,db=DB):
    if file_hash(path)!=digest:raise ValueError('Save changed during export')
    initialize(db)
    note="FM keeps no Premier League table between seasons. Earlier league snapshots are unchanged; the stage resumes when the new season's table exists."
    with closing(connection(db)) as con,con:
        con.execute('INSERT OR IGNORE INTO league_offseason_skips VALUES(?,?,?,?,?,?)',(digest,iso(day),gap['finished_season'],gap['next_season'],gap['next_start'],note))
    summary=dict(status='offseason_skipped',date=iso(day),**gap)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def export_snapshot(path,db=DB):
    import fmsave
    digest=file_hash(path)
    if has_snapshot(digest,db):return {'status':'already_imported','sha256':digest}
    skipped=offseason_skip(digest,db)
    if skipped:return {**skipped,'status':'offseason_skipped'}
    print("Checking Premier League snapshot: "+path.name,flush=True)
    with closing(connection(db)) as con:
        tracked={r[0] for r in con.execute('SELECT club_uid FROM league_teams')} if con.execute("SELECT 1 FROM sqlite_master WHERE name='league_teams'").fetchone() else set()
    with fmsave.open(path,strict=True) as save:
        if not save.info.known_build:raise ValueError('Unknown save build')
        day=save.info.game_date
        comps={c.id:c.database_id for c in save.competitions()}
        try:
            found=save.league_tables();rejected=None
        except fmsave.GateCheckError as exc:
            if not only_division_gate(exc):raise
            found=[];rejected=exc
        tables=[t for t in found if comps.get(t.competition_id)==COMPETITION_DB_ID
                and t.club_count==20 and all(r.team_slot==0 and r.rounds_per_venue==19 for r in t.rows)]
        if not tables:
            gap=offseason(comps,save.fixtures(),day)
            if gap:return record_offseason(path,digest,day,gap,db)
        if rejected:raise ValueError(str(rejected))
        if len(tables)!=1:raise ValueError("Could not uniquely identify the 20-club Premier League table. Nothing was written.")
        table=tables[0]
        if len({r.club_uid for r in table.rows})!=20 or any(r.club_uid is None for r in table.rows):raise ValueError('Club membership unavailable')
        standings={r.club_uid:project(r,STANDING_FIELDS) for r in table.rows}
        fixtures=save.fixtures()
        period=infer_season(table,fixtures,day)
        tracked|=set(standings)
        clubs={c.uid:c for c in save.clubs() if c.uid in tracked}
        all_players=save.players()
        all_stats=save.player_season_stats()
        roster_by_club=defaultdict(list);stats_by_team=defaultdict(list)
        for p in all_players:
            if p.club_uid in tracked and p.team_slot==0:roster_by_club[p.club_uid].append(squad_projection(p))
        for r in all_stats:
            if r.club_uid in tracked and r.team_slot==0 and str(r.kind) in KINDS:stats_by_team[r.team_id].append(project(r,SEASON_FIELDS))
        teams=[]
        for uid in sorted(tracked):
            if uid not in clubs:raise ValueError("A tracked club was not found in the new save. Existing snapshots were retained.")
            c=clubs[uid]
            first=[t for t in c.teams if t.slot==0 and t.club_uid==uid and not t.is_affiliate]
            if len(first)!=1:raise ValueError('First team could not be identified')
            team_id=first[0].team_id
            if uid in standings and team_id!=standings[uid]['team_id']:raise ValueError('First-team ID mismatch')
            stats=stats_by_team[team_id]
            league=[r for r in stats if r['kind']=='league']
            if uid in standings and standings[uid]['played']>0 and not league and not all(r.played==38 for r in table.rows):raise ValueError("A Premier League club has played matches but lacks league statistics. Existing snapshots were retained.")
            teams.append(dict(club_uid=uid,club_unique_id=c.unique_id,club_name=c.name,team_id=team_id,in_premier=uid in standings,
                roster=roster_by_club[uid],stats=stats,standing=standings.get(uid),coverage=dict(
                    roster_count=len(roster_by_club[uid]),stats_by_kind=dict(Counter(r['kind'] for r in stats)),league_player_count=len(league),
                    league_stat_null_counts={k:sum(r[k] is None for r in league) for k in COUNTS},
                    note="Roster represents the first team at this date. Statistics can include players who appeared before leaving or moving squads. Missing values remain null; goalkeeper and outfield metrics differ. league for a non-Premier League club refers to its own competition and must not enter Premier League rankings.")))
        complete=all(r.played==38 for r in table.rows)
    previous=[];previous_meta=None
    if db.exists():
        with closing(connection(db)) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone():
                previous_meta=con.execute('SELECT * FROM league_snapshots WHERE game_date<? AND season=? AND league_complete=1 ORDER BY game_date DESC,sha256 DESC LIMIT 1',(iso(day),period)).fetchone()
                if previous_meta:
                    previous=[dict(club_uid=r['club_uid'],stats=json.loads(r['stats_json'])) for r in con.execute('SELECT club_uid,stats_json FROM league_team_snapshots WHERE sha256=?',(previous_meta['sha256'],))]
    reset=bool(previous_meta and previous_meta['league_complete'] and previous_meta['season']==period and detect_reset(previous,teams))
    if reset:
        year=int(period[:4])+1;period=f'{year}/{str(year+1)[-2:]}';complete=False
        for t in teams:t['standing']=None
    if not reset and any(t['standing'] and t['standing']['played']>0 and not t['coverage']['league_player_count'] for t in teams):
        raise ValueError("Statistics are missing without a confirmed season reset. Existing snapshots were retained.")
    note="Season is reconciled from the Premier League fixture season_start_year and table match counts; the competition ID is identified within this save. Only visible roster, attributes and season statistics are stored, not contracts, injuries, hidden ability or personal history."
    if reset:note+=" A post-season team-wide cumulative reset was detected. A new season was opened without copying the old table."
    payload=dict(sha256=digest,game_date=iso(day),season=period,competition_db_id=COMPETITION_DB_ID,
                 league_complete=complete,reset_detected=reset,note=note,teams=teams)
    if file_hash(path)!=digest:raise ValueError('Save changed during export')
    created=store(payload,db)
    summary=dict(status='imported' if created else 'already_imported',date=iso(day),season=period,teams=len(teams),
                 premier_teams=sum(t['in_premier'] for t in teams),roster=sum(len(t['roster']) for t in teams),
                 statistics=sum(len(t['stats']) for t in teams),league_complete=complete)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


SOURCE_SQL="""SELECT COALESCE(
 (SELECT source_sha256 FROM league_frozen_seasons WHERE season=? AND as_of<=?),
 (SELECT sha256 FROM league_snapshots WHERE season=? AND game_date<=? ORDER BY game_date DESC,sha256 DESC LIMIT 1))"""


def read_teams(period=None,club_uid=None,db=DB,through_date=None):
    with closing(connection(db)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone():return []
        if through_date:
            # Historical chat queries cannot see a later snapshot or later freeze decision.
            sql="SELECT t.*,s.game_date,s.season,s.league_complete,'as_of' AS archive_status FROM league_team_snapshots t JOIN league_snapshots s ON s.sha256=t.sha256 WHERE s.sha256=("+SOURCE_SQL+")"
            rows=con.execute(sql,(period,through_date,period,through_date)).fetchall()
        else:
            rows=con.execute('SELECT * FROM v_league_team_season WHERE (? IS NULL OR season=?)',(period,period)).fetchall()
        return [{**{k:r[k] for k in ('sha256','club_uid','club_name','team_id','in_premier','game_date','season','league_complete','archive_status')},
                 'roster':json.loads(r['roster_json']),'stats':json.loads(r['stats_json']),
                 'standing':json.loads(r['standing_json']),'coverage':json.loads(r['coverage_json'])}
                for r in rows if club_uid is None or r['club_uid']==club_uid]


def backfill():
    from src.archive import snapshots
    initialize()
    backup=ROOT/'db/backups'/('before-league-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
    backup.parent.mkdir(exist_ok=True)
    with closing(connection()) as source,closing(sqlite3.connect(backup)) as target:source.backup(target)
    failures=[]
    for snapshot in reversed(snapshots()):
        try:export_snapshot(ROOT/'data/saves'/snapshot['filename'])
        except Exception as exc:
            failures.append(dict(date=snapshot['game_date'],error=str(exc)))
            print("Premier League snapshot import failed: "+snapshot['game_date']+' · '+str(exc),flush=True)
    (ROOT/'data/checks/league_backfill.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8')
    if failures:raise SystemExit(1)


if __name__=='__main__':backfill()
