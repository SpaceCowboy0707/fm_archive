"""Native workspace archive views over the existing, validated repositories.

No model calls. Snapshot-scoped views cannot read observations from the future.
League views deliberately use their own season/freeze policy, as in the archive UI.
"""
import json
import subprocess
import sys
import threading
from contextlib import closing
from functools import lru_cache

from src import analytics as an
from src.archive import DB, snapshots, squad, history
from src.conversations import load_conversation, matching_passages
from src.league_archive import connection, read_teams
from src.lore import load_lore
from src.safe_export import ROOT
from src.transfers import read_transfers
from src.movements import read_movements


@lru_cache(maxsize=2)
def _data(stamp):
    return an.datasets()


def context(snapshot_id=None):
    available = snapshots()
    snap = next((s for s in available if str(s['id']) == str(snapshot_id)), None) if snapshot_id else (available[0] if available else None)
    if not snap:
        raise ValueError('Snapshot not found. Import a save first.')
    data = [d for d in _data(DB.stat().st_mtime_ns) if d['snapshot']['date'] <= snap['game_date']]
    return snap, data


def finances(data):
    return [{**{k: v for k, v in p.items() if k != 'player'}, 'player_name': p['player']['name'],
             'identity_key': p['player']['identity_key'], 'contract_end': p['player']['contract_end'],
             'club_name': p['player']['club_name'], 'as_of': d['snapshot']['date']}
            for d in data for p in d['players']]


def roster(snap, data):
    rows = [{**p, 'membership': 'registered'} for p in squad(snap['id'])]
    current = next((d for d in data if d['snapshot']['sha256'] == snap['sha256']), None)
    if current:
        known = {r['identity_key'] for r in rows}
        rows += [{**p['player'], 'membership': 'loan_out'} for p in current['players']
                 if p['membership'] == 'loan_out' and p['player']['identity_key'] not in known]
    return sorted(rows, key=lambda p: (p['name'] or '').casefold())


def overview(page, snapshot_id=None, period=None, identity=None):
    if page == 'transfers':
        rows, batches = read_transfers()
        images = {k: {'url': '/api/archive/image?id=' + k} for b in batches for k in b['images']}
        return dict(rows=rows, images=images, movements=read_movements(DB))
    if page == 'stories':
        return dict(rows=load_lore())
    if page == 'originals':
        data = load_conversation()
        return dict(source=data, passages=matching_passages(data))
    if page == 'league':
        with closing(connection()) as con:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone():
                return dict(periods=[], teams=[])
            periods = [r[0] for r in con.execute('SELECT DISTINCT season FROM league_snapshots ORDER BY season DESC')]
            chosen = period or (periods[0] if periods else None)
            if chosen not in periods:
                return dict(periods=periods, teams=[])
            freeze = con.execute('SELECT * FROM league_frozen_seasons WHERE season=?', (chosen,)).fetchone()
        return dict(periods=periods, period=chosen, teams=read_teams(chosen), frozen=dict(freeze) if freeze else None)
    snap, data = context(snapshot_id)
    base = dict(snapshot={k: snap[k] for k in ('id', 'game_date', 'club_uid', 'club_name', 'sha256')})
    if page == 'squad':
        return dict(**base, rows=roster(snap, data))
    if page == 'player':
        player = next((p for p in roster(snap, data) if p['identity_key'] == identity), None)
        if not player:
            raise ValueError('Player not found in this snapshot.')
        return dict(**base, player=player,
                    seasons=an.aggregate_seasons([r for r in an.season_rows(data) if r['identity_key'] == identity], ('period', 'kind', 'club_name')),
                    matches=[r for r in an.match_rows(data) if r['identity_key'] == identity],
                    injuries=[r for r in an.latest_rows(data, 'injuries', ('identity_key', 'player_uid', 'kind', 'date', 'team_id', 'type_id')) if r['identity_key'] == identity],
                    contracts=[r for r in an.latest_rows(data, 'contracts', ('identity_key', 'club_uid', 'start', 'end')) if r['identity_key'] == identity],
                    finances=[r for r in finances(data) if r['identity_key'] == identity],
                    history=history(identity, through_date=snap['game_date']),
                    stories=[r for r in load_lore() if identity in r['player_keys']],
                    passages=matching_passages(load_conversation(), person=player['name']))
    if page == 'statistics':
        stats = an.season_rows(data)
        groups = ('identity_key', 'player_name', 'period', 'kind', 'club_uid', 'club_name', 'team_slot')
        rows = an.aggregate_seasons(stats, groups)
        combined = an.aggregate_seasons(stats, tuple(k for k in groups if k != 'period'))
        injuries = an.latest_rows(data, 'injuries', ('identity_key', 'player_uid', 'kind', 'date', 'team_id', 'type_id'))
        contracts = an.latest_rows(data, 'contracts', ('identity_key', 'club_uid', 'start', 'end'))
        matches, fixtures = an.match_rows(data), an.fixture_rows(data)
        names = {}
        manual = ROOT / 'data/manual/competition_names.json'
        if manual.exists():
            names.update(json.loads(manual.read_text(encoding='utf-8')))
        for d in data:
            for c in d['competitions']:
                names.setdefault(c['competition_key'], c['name'] or c['competition_key'])
        periods = sorted({r['period'] for r in stats + matches + fixtures if r.get('period')}, reverse=True)
        coverage = []
        for p in periods:
            sr = [r for r in stats if r['period'] == p and r['club_uid'] == snap['club_uid'] and r['team_slot'] == 0]
            mr = [r for r in matches if r['period'] == p and r['own_club_uid'] == snap['club_uid'] and r['own_team_slot'] == 0]
            fr = [r for r in fixtures if r['period'] == p and ((r['home_club_uid'] == snap['club_uid'] and r['home_team_slot'] == 0) or (r['away_club_uid'] == snap['club_uid'] and r['away_team_slot'] == 0))]
            coverage.append(dict(period=p, retained_played_fixtures=sum(bool(r['played']) for r in fr), retained_appearances=len(mr), valid_details=sum(bool(r['has_stats'] and r['stats_in_range']) for r in mr), observed_through=max((r['as_of'] for r in sr), default=None)))
        contributions=an.aggregate_seasons(stats, ('period','kind','club_uid','club_name','team_slot'))
        combined_contributions=an.aggregate_seasons(stats, ('kind','club_uid','club_name','team_slot'))
        match_totals=an.aggregate_matches(matches, ('player_name','identity_key','period','competition_key','own_club_uid','own_club_name','own_team_slot'))
        return dict(**base, rows=rows, combined=combined, contributions=contributions, combined_contributions=combined_contributions,
                    match_totals=match_totals, fixture_totals=an.aggregate_fixtures(fixtures,snap['club_uid']),
                    periods=periods, matches=matches, fixtures=fixtures,
                    injuries=injuries, contracts=contracts, finances=finances(data[-1:]), coverage=coverage, competitions=names)
    if page == 'checks':
        current = next((d for d in data if d['snapshot']['sha256'] == snap['sha256']), None)
        return dict(**base, checks=json.loads(snap['validation_json']), extended=current['checks'] if current else [],
                    build=snap['build'], fmsave_version=snap['fmsave_version'],
                    missing_names=sum(not p['name'] for p in squad(snap['id'])),
                    missing_contracts=sum(not p['contract_end'] for p in squad(snap['id'])))
    raise ValueError('Unknown archive page.')


def evidence_image(image_id):
    _, batches = read_transfers()
    records = {k: v for b in batches for k, v in b['images'].items()}
    if image_id not in records:
        raise ValueError('Evidence image not found.')
    path = (ROOT / records[image_id]['path']).resolve()
    if not path.is_relative_to((ROOT / 'data/evidence').resolve()) or path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('Invalid evidence image.')
    return path


_sync_lock = threading.Lock()
_sync_state = dict(state='idle', output='')


def sync_status():
    with _sync_lock:
        return dict(_sync_state)


def start_sync():
    with _sync_lock:
        if _sync_state['state'] == 'running':
            return dict(_sync_state)
        _sync_state.update(state='running', output='')

    def run():
        try:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'src.sync_save'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=1800)
            state, output = ('complete' if result.returncode == 0 else 'failed'), (result.stdout + '\n' + result.stderr)[-24000:]
        except Exception as exc:
            state, output = 'failed', str(exc)
        _data.cache_clear()
        with _sync_lock:
            _sync_state.update(state=state, output=output)
    threading.Thread(target=run, daemon=True).start()
    return sync_status()
