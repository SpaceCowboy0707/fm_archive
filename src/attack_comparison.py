"""Whole-snapshot attacking benchmarks; no model-side pagination or hidden attributes."""
import math
from collections import Counter

METRICS=('goals','assists','expected_goals','expected_assists','shots','shots_on_target',
         'shots_outside_box','key_passes','clear_cut_chances_created','progressive_passes',
         'dribbles','crosses_attempted','crosses_completed','passes_attempted','passes_completed','offsides')
GROUPS={'GK':"Goalkeeper",'DC':"Centre-back",'DL':"Full-back",'DR':"Full-back",'WBL':"Full-back",'WBR':"Full-back",
        'DM':"Midfielder",'MC':"Midfielder",'AMC':"Attacking midfielder",'AML':"Winger",'AMR':"Winger",'ML':"Winger",'MR':"Winger",'STC':"Striker"}

def number(x):
    return type(x) in (int,float) and math.isfinite(x) and x>=0

def build(teams,target_uid,min_minutes):
    players=[];missing_positions=0
    for team in teams:
        roster={p['uid']:p for p in team['roster']}
        stats={};duplicates=set()
        for row in team['stats']:
            if row['kind']!='league':continue
            uid=row['player_uid']
            if uid in stats:duplicates.add(uid)
            stats[uid]=row
        for uid in sorted(set(roster)|set(stats)):
            p=roster.get(uid,{});s=stats.get(uid);positions=p.get('natural_positions') or []
            groups=sorted({GROUPS[x] for x in positions if x in GROUPS})
            if not groups:missing_positions+=1
            minutes=s.get('minutes') if s else None
            usable=s is not None and uid not in duplicates
            raw=[s.get(k) if usable else None for k in METRICS]
            per90=[round(v*90/minutes,4) if number(v) and number(minutes) and minutes>0 else None for v in raw]
            status='duplicate_statistics' if uid in duplicates else 'no_league_statistics' if s is None else 'missing_minutes' if not number(minutes) else 'zero_minutes' if minutes==0 else 'below_min_minutes' if minutes<min_minutes else 'eligible'
            players.append(dict(player_uid=uid,name=p.get('name') or (s or {}).get('player_name'),club_uid=team['uid'],
                in_current_roster=uid in roster,positions=positions,groups=groups,minutes=minutes,status=status,
                totals=raw,per90=per90,benchmarks=[]))
    target=[p for p in players if p['club_uid']==target_uid]
    for p in target:
        if p['status']!='eligible':continue
        for group in p['groups']:
            peers=[x for x in players if group in x['groups'] and x['status']=='eligible']
            ranks=[];percentiles=[];counts=[]
            for i,value in enumerate(p['per90']):
                values=[x['per90'][i] for x in peers if x['per90'][i] is not None]
                counts.append(len(values))
                ranks.append(1+sum(v>value for v in values) if value is not None else None)
                percentiles.append(round(100*(sum(v<value for v in values)+.5*sum(v==value for v in values))/len(values),1) if value is not None and values else None)
            p['benchmarks'].append(dict(group=group,eligible_players=len(peers),metric_sample_counts=counts,rank_desc=ranks,percentile=percentiles))
    return dict(rows=target,total=len(target),offset=0,next_offset=None,metric_columns=list(METRICS),
        coverage=dict(teams=len(teams),players=len(players),missing_position_players=missing_positions,status_counts=dict(Counter(p['status'] for p in players))),
        min_minutes=min_minutes,
        notes="totals/per90 and each benchmark array align with metric_columns. All target-team players are retained. Comparisons use league data from one snapshot; roster and statistics are unioned. Former players without position data remain listed but unranked. Multiple natural positions enter each applicable group; these are not actual match roles, and DM/MC share one group. Zero minutes, low minutes and duplicate statistics are excluded from ranking. Missing is not zero. rank_desc is descending competition rank per 90 (ties share ranks); percentile is the proportion below plus half the tied proportion. Higher is not always better, particularly shots and offsides. No overall ability score or adjustment for opponent, tactics, actual role or possession.")
