"""Visible financial and sporting records; never serialize whole fmsave objects."""
from __future__ import annotations
from src.i18n import INPUT_ALIASES
import json, sqlite3, warnings
from pathlib import Path
from datetime import date, datetime, timezone
from collections import defaultdict
from importlib.metadata import version
from src.safe_export import ROOT, file_hash, iso, project_player, PLAYER_FIELDS, ATTRIBUTES, check_keys
from src.archive import DB, connect, import_payload

COUNTS = tuple('''starts substitute_appearances minutes rated_appearances player_of_the_match
goals assists expected_goals expected_assists shots shots_on_target shots_outside_box goals_outside_box
free_kick_shots penalties_taken penalties_scored passes_attempted passes_completed progressive_passes
key_passes open_play_key_passes clear_cut_chances_created crosses_attempted crosses_completed
open_play_crosses_attempted open_play_crosses_completed dribbles offsides distance_km high_intensity_sprints
aerial_challenges_attempted headers_won key_headers tackles_attempted tackles_completed key_tackles
interceptions possession_won pressures_attempted pressures_completed blocks shots_blocked clearances
fouls_made fouls_against yellow_cards red_cards mistakes_leading_to_goal clean_sheets goals_allowed
saves_held saves_parried saves_tipped shots_on_target_faced expected_goals_prevented'''.split())
SEASON_FIELDS = ('player_uid','player_name','kind','team_id','club_uid','club_name','team_slot',*COUNTS,'average_rating')
MATCH_FIELDS = tuple('''player_uid player_name date competition_id opponent_team_id opponent_club_uid
opponent_club_name has_stats minutes left_at_minute goals assists rating passes_attempted passes_completed stats_in_range'''.split())
FIXTURE_FIELDS = tuple('''stage_id competition_id competition_name round_index date season_start_year
home_team_id home_club_uid home_club_name home_team_slot away_team_id away_club_uid away_club_name
away_team_slot home_goals away_goals played stadium_name match_record_id'''.split())
INJURY_FIELDS = tuple('kind player_uid player_name date team_id club_uid club_name team_slot type_id type_name cause severity'.split())
CHAIN_FIELDS = tuple('club_uid club_name team_id wage start end has_terms'.split())
FINANCE_FIELDS = frozenset('player membership wage_weekly transfer_value transfer_value_state currency loan_start loan_end contract_club_name contract_start'.split())
EXTRA = {
    'season_stats':frozenset((*SEASON_FIELDS,'identity_key','period')),
    'matches':frozenset((*MATCH_FIELDS,'identity_key','competition_key','own_club_uid','own_club_name','own_team_slot','attribution','period')),
    'fixtures':frozenset((*FIXTURE_FIELDS,'competition_key','period')),
    'injuries':frozenset((*INJURY_FIELDS,'identity_key')),
    'contracts':frozenset((*CHAIN_FIELDS,'identity_key','player_name')),
    'competitions':frozenset(('id','database_id','name','competition_key')),
}
KIND_NAMES={'overall':"Club season total",'league':"League",'cup':"Domestic cups",'continental':"Continental competitions",
 'non_competitive':"Non-competitive",'international':"International season",'calendar_year_overall':"Club calendar year",'calendar_year_international':"International calendar year"}


def scalar(value):
    if isinstance(value,str): return str(value)
    if value is None or isinstance(value,(int,float,bool)): return value
    if isinstance(value,date): return value.isoformat()
    if hasattr(value,'label_text'): return value.label_text
    raise TypeError('Only explicitly supported visible scalars may be exported')


def project(record,fields):
    return {key:scalar(getattr(record,key)) for key in fields}


def season(day):
    value=date.fromisoformat(str(day))
    start=value.year-(value.month<7)
    return f'{start}/{str(start+1)[-2:]}'


def validate(data):
    check_keys(data,frozenset(('schema_version','snapshot','players','checks',*EXTRA)))
    if data['schema_version'] != 1: raise ValueError('Unsupported analytics version')
    check_keys(data['snapshot'],frozenset(('sha256','date','club_uid','source_file')))
    for player in data['players']:
        check_keys(player,FINANCE_FIELDS)
        check_keys(player['player'],PLAYER_FIELDS)
        check_keys(player['player']['attributes'],frozenset(ATTRIBUTES))
    for table,fields in EXTRA.items():
        for row in data[table]:
            check_keys(row,fields)
            if any(not (v is None or type(v) in (str,int,float,bool)) for v in row.values()):
                raise ValueError('Unexpected nested value in sporting records')
    for row in data['checks']:
        check_keys(row,frozenset(('reader','status','record_count','note')))


def import_extended(path:Path,db:Path=DB):
    import fmsave
    digest=file_hash(path)
    with connect(db) as con:
        con.execute('CREATE TABLE IF NOT EXISTS analytics_snapshots(sha256 TEXT PRIMARY KEY,game_date TEXT NOT NULL,payload_json TEXT NOT NULL)')
        if con.execute('SELECT 1 FROM analytics_snapshots WHERE sha256=?',(digest,)).fetchone():
            print(json.dumps({'status':'already_imported','sha':digest[:12]}),flush=True)
            return
    print(json.dumps({'status':'reading','file':path.name}),flush=True)
    checks=[]
    with fmsave.open(path,strict=True) as save:
        if not save.info.known_build: raise ValueError('Unknown FM build; import stopped')
        managed=save.managed_clubs()
        if len(managed)!=1 or not any(x in managed[0].club_name.casefold() for x in INPUT_ALIASES['club_aliases']):
            raise ValueError('Not a Leicester save')
        club=managed[0]; uid=club.club_uid; day=save.info.game_date
        all_players=save.players()
        all_stats=save.player_season_stats()
        associated={r.player_uid for r in all_stats if r.club_uid==uid}
        selected=[]
        for player in all_players:
            prior=player.contract and any(c.club_uid==uid and (c.start is None or c.start<=day) for c in player.contract.chain)
            if player.club_uid==uid or (player.on_loan and player.loan_parent_club_uid==uid) or player.uid in associated or prior:
                selected.append(player)
        people={p.uid:project_player(p) for p in selected}
        data={'schema_version':1,'snapshot':{'sha256':digest,'date':iso(day),'club_uid':uid,'source_file':path.name},
              'players':[],'checks':checks,**{table:[] for table in EXTRA}}
        for p in selected:
            membership='registered' if p.club_uid==uid else 'loan_out' if p.on_loan and p.loan_parent_club_uid==uid else 'historical_link'
            data['players'].append({'player':people[p.uid],'membership':membership,
                'wage_weekly':p.contract.wage if p.contract else None,'transfer_value':p.transfer_value,
                'transfer_value_state':str(p.transfer_value_state),'currency':'save_base_currency_unverified',
                'loan_start':iso(p.loan_start),'loan_end':iso(p.loan_end),
                'contract_club_name':p.contract.club_name if p.contract else None,'contract_start':iso(p.contract.start) if p.contract else None})
            if p.contract:
                for c in p.contract.chain:
                    data['contracts'].append({**project(c,CHAIN_FIELDS),'identity_key':people[p.uid]['identity_key'],'player_name':p.name})
        for row in all_stats:
            if row.player_uid in people:
                kind=str(row.kind)
                data['season_stats'].append({**project(row,SEASON_FIELDS),'identity_key':people[row.player_uid]['identity_key'],
                    'period':str(day.year) if kind.startswith('calendar_year') else season(day)})
        competitions={c.id:c for c in save.competitions()}
        def comp_key(cid):
            comp=competitions.get(cid)
            return f'db:{comp.database_id}' if comp and comp.database_id is not None else f'stage:{cid}'
        fixtures=save.fixtures()
        match_index=defaultdict(list)
        kept_clubs={uid}|{p.club_uid for p in selected if p.on_loan and p.loan_parent_club_uid==uid}
        for f in fixtures:
            if f.date and f.played:
                match_index[(f.date,f.competition_id,f.away_team_id)].append((f.home_club_uid,f.home_club_name,f.home_team_slot))
                match_index[(f.date,f.competition_id,f.home_team_id)].append((f.away_club_uid,f.away_club_name,f.away_team_slot))
            if f.home_club_uid in kept_clubs or f.away_club_uid in kept_clubs:
                period=f'{f.season_start_year}/{str(f.season_start_year+1)[-2:]}' if f.season_start_year is not None else season(f.date) if f.date else None
                data['fixtures'].append({**project(f,FIXTURE_FIELDS),'competition_key':comp_key(f.competition_id),'period':period})
        all_matches=save.player_match_stats()
        for row in all_matches:
            if row.player_uid not in people: continue
            candidates=set(match_index.get((row.date,row.competition_id,row.opponent_team_id),[]))
            own=next(iter(candidates)) if len(candidates)==1 else (None,None,None)
            data['matches'].append({**project(row,MATCH_FIELDS),'identity_key':people[row.player_uid]['identity_key'],
                'competition_key':comp_key(row.competition_id),'own_club_uid':own[0],'own_club_name':own[1],
                'own_team_slot':own[2],'attribution':'matched_fixture' if len(candidates)==1 else 'unresolved',
                'period':season(row.date)})
        used={r['competition_id'] for t in ('fixtures','matches') for r in data[t]}
        data['competitions']=[{'id':c.id,'database_id':c.database_id,'name':c.name,'competition_key':comp_key(c.id)} for c in competitions.values() if c.id in used]
        checks.extend({'reader':name,'status':'ok','record_count':count,'note':'strict=True; reader checks passed'} for name,count in
          [('managed_clubs',len(managed)),('players',len(all_players)),('contracts',sum(p.contract is not None for p in all_players)),
           ('player_season_stats',len(all_stats)),('fixtures',len(fixtures)),('player_match_stats',len(all_matches))])
        core={'schema_version':1,'snapshot':{'sha256':digest,'filename':path.name,'game_date':iso(day),'build':save.info.build,
          'fmsave_version':version('fmsave'),'exported_at':datetime.now(timezone.utc).isoformat()},
          'club':{'uid':uid,'name':club.club_name,'manager':club.manager_name},
          'players':[people[p.uid] for p in selected if p.club_uid==uid],
          'validation':[{k:r[k] for k in ('reader','status','record_count')} for r in checks]}
    # Injury names may fail while dated histories remain valid. Only that known dependency
    # warning is accepted; every other injury warning/error withholds the injury table.
    try:
        with warnings.catch_warnings(record=True) as caught, fmsave.open(path,strict=False) as save:
            warnings.simplefilter('always')
            injuries=save.injuries()
            unacceptable=[w for w in caught if not str(w.message).startswith('injury_types failed checks:')]
            if unacceptable: raise ValueError('Injury checks failed beyond missing type names')
            for row in injuries:
                if row.player_uid in people or row.club_uid==uid:
                    data['injuries'].append({**project(row,INJURY_FIELDS),'identity_key':people.get(row.player_uid,{}).get('identity_key')})
            checks.append({'reader':'injuries','status':'partial' if caught else 'ok','record_count':len(data['injuries']),
                           'note':"Injury names missing; history dates are occurrence dates and typed dates are expected return dates" if caught else 'Injury checks passed'})
    except (fmsave.FmsaveError,ValueError):
        data['injuries']=[]
        checks.append({'reader':'injuries','status':'failed','record_count':0,'note':"Injury validation failed; records were not imported"})
    if file_hash(path)!=digest: raise ValueError('Save changed while importing')
    validate(data)
    target=ROOT/'data/raw/extended'/f'analytics_{data["snapshot"]["date"]}_{digest[:12]}.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    import_payload(core,db)
    with connect(db) as con,con:
        con.execute('INSERT INTO analytics_snapshots VALUES(?,?,?)',(digest,iso(day),json.dumps(data,ensure_ascii=False)))
    print(json.dumps({'status':'imported','date':iso(day),'members':len(data['players']),
       **{t:len(data[t]) for t in EXTRA}}),flush=True)


def datasets(db:Path=DB):
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='analytics_snapshots'").fetchone(): return []
        result=[json.loads(r[0]) for r in con.execute('SELECT payload_json FROM analytics_snapshots ORDER BY game_date,sha256')]
    for data in result: validate(data)
    return result


def latest_rows(data,table,keys):
    """Cumulative snapshots replace earlier observations, never sum them."""
    result={}
    for snap in sorted(data,key=lambda x:x['snapshot']['date']):
        for row in snap[table]:
            key=tuple(row[k] for k in keys)
            result[key]={**row,'as_of':snap['snapshot']['date']}
    return list(result.values())


def season_rows(data):
    return [r for r in latest_rows(data,'season_stats',('identity_key','period','kind','team_id'))
            if not r['kind'].startswith('calendar_year') and '/' in r['period']]


def match_rows(data):
    # Prefer rows whose stats survived even when a later save dropped the detailed block.
    result={}
    for snap in sorted(data,key=lambda x:x['snapshot']['date']):
        for r in snap['matches']:
            key=(r['identity_key'],r['date'],r['competition_key'],r['opponent_team_id'])
            prev=result.get(key)
            item={**r,'as_of':snap['snapshot']['date']}
            if prev:
                if (bool(prev['has_stats']),bool(prev['stats_in_range'])) > (bool(r['has_stats']),bool(r['stats_in_range'])):
                    item=prev.copy()
                if r['own_club_uid'] is not None:
                    item.update({k:r[k] for k in ('own_club_uid','own_club_name','own_team_slot','attribution')})
                if item['own_club_uid'] is None and prev['own_club_uid'] is not None:
                    item.update({k:prev[k] for k in ('own_club_uid','own_club_name','own_team_slot','attribution')})
            result[key]=item
    return list(result.values())


def aggregate_seasons(rows,group_keys=('period','kind','club_uid','club_name')):
    groups=defaultdict(list)
    for row in rows: groups[tuple(row[k] for k in group_keys)].append(row)
    result=[]
    for key,group in groups.items():
        out=dict(zip(group_keys,key));out['players']=len({r['identity_key'] for r in group})
        for field in COUNTS:
            values=[r[field] for r in group if r[field] is not None]
            # Unknown component prevents claiming a complete total for that field.
            out[field]=sum(values) if len(values)==len(group) else None
        out['appearances']=sum(r['starts']+r['substitute_appearances'] for r in group)
        rated=[r for r in group if r['average_rating'] is not None and r['rated_appearances']>0]
        denom=sum(r['rated_appearances'] for r in rated)
        out['average_rating']=sum(r['average_rating']*r['rated_appearances'] for r in rated)/denom if denom else None
        for field in ('goals','assists','shots','dribbles','key_passes','tackles_completed','distance_km','expected_goals','expected_assists'):
            out[field+'_per_90']=out[field]*90/out['minutes'] if out['minutes'] and out[field] is not None else None
        for name,part,whole in [('pass_completion_percent','passes_completed','passes_attempted'),('tackle_completion_percent','tackles_completed','tackles_attempted'),('shots_on_target_percent','shots_on_target','shots')]:
            out[name]=100*out[part]/out[whole] if out[whole] and out[part] is not None else None
        out['oldest_observation']=min(r['as_of'] for r in group);out['newest_observation']=max(r['as_of'] for r in group)
        result.append(out)
    return result


def fixture_rows(data):
    return latest_rows(data,'fixtures',('date','competition_key','home_team_id','away_team_id'))


def aggregate_matches(rows,group_keys=('period','competition_key','own_club_name')):
    """Retained match records, NOT complete career/season totals."""
    groups=defaultdict(list)
    for row in rows: groups[tuple(row[k] for k in group_keys)].append(row)
    result=[]
    for key,group in groups.items():
        out=dict(zip(group_keys,key))
        out['retained_appearances']=len(group)
        valid=[r for r in group if r['has_stats'] and r['stats_in_range']]
        out['detailed_appearances']=len(valid)
        for field in ('minutes','goals','assists','passes_attempted','passes_completed'):
            vals=[r[field] for r in valid if r[field] is not None]
            out[field]=sum(vals) if vals else None
            out[field+'_coverage']=len(vals)
        ratings=[r['rating'] for r in valid if r['rating'] is not None]
        out['average_rating']=sum(ratings)/len(ratings) if ratings else None
        out['pass_completion_percent']=100*out['passes_completed']/out['passes_attempted'] if out['passes_attempted'] and out['passes_completed'] is not None else None
        result.append(out)
    return result


def aggregate_fixtures(rows,club_uid):
    groups=defaultdict(list)
    for row in rows:
        home=row['home_club_uid']==club_uid
        if not home and row['away_club_uid']!=club_uid: continue
        slot=row['home_team_slot'] if home else row['away_team_slot']
        groups[(row['period'],row['competition_key'],slot)].append((row,home))
    result=[]
    for (period,competition,slot),items in groups.items():
        scored=[(r,home) for r,home in items if r['played'] and r['home_goals'] is not None and r['away_goals'] is not None]
        scores=[(r['home_goals'],r['away_goals']) if home else (r['away_goals'],r['home_goals']) for r,home in scored]
        result.append({'period':period,'competition_key':competition,'team_slot':slot,
           "Retained played fixtures":sum(bool(r['played']) for r,_ in items),"Fixtures with scores":len(scores),
           "Wins":sum(a>b for a,b in scores),"Draws":sum(a==b for a,b in scores),"Losses":sum(a<b for a,b in scores),
           "Goals":sum(a for a,b in scores) if scores else None,"Goals conceded":sum(b for a,b in scores) if scores else None,
           "Retained upcoming fixtures":sum(not r['played'] for r,_ in items)})
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('save',type=Path)
    import_extended(parser.parse_args().save)
