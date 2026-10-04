"""Chinese browsing views over allowlisted sporting and financial records."""
import json
from collections import Counter
import pandas as pd
from src.i18n import st
from src.safe_export import ROOT
from src.analytics import (datasets, season_rows, match_rows, fixture_rows, latest_rows,
                           aggregate_seasons, aggregate_matches, aggregate_fixtures, KIND_NAMES, season)

LABELS=dict(zip('''starts substitute_appearances minutes rated_appearances player_of_the_match goals assists expected_goals expected_assists shots shots_on_target shots_outside_box goals_outside_box free_kick_shots penalties_taken penalties_scored passes_attempted passes_completed progressive_passes key_passes open_play_key_passes clear_cut_chances_created crosses_attempted crosses_completed open_play_crosses_attempted open_play_crosses_completed dribbles offsides distance_km high_intensity_sprints aerial_challenges_attempted headers_won key_headers tackles_attempted tackles_completed key_tackles interceptions possession_won pressures_attempted pressures_completed blocks shots_blocked clearances fouls_made fouls_against yellow_cards red_cards mistakes_leading_to_goal clean_sheets goals_allowed saves_held saves_parried saves_tipped shots_on_target_faced expected_goals_prevented'''.split(),
"Starts Substitute_appearances Minutes Rated_appearances Player_of_the_match Goals Assists xG xA Shots Shots_on_target Shots_outside_box Goals_outside_box Free_kick_shots Penalty_attempts Penalty_goals Pass_attempts Completed_passes Progressive_passes Key_passes Open_play_key_passes Clear_cut_chances_created Cross_attempts Completed_crosses Open_play_cross_attempts Open_play_completed_crosses Dribbles Offsides Distance_km High_intensity_sprints Aerial_attempts Aerial_wins Key_headers Tackle_attempts Tackles_won Key_tackles Interceptions Possession_won Press_attempts Successful_presses Blocks Shot_blocks Clearances Fouls Fouls_suffered Yellow_cards Red_cards Errors_leading_to_goals Clean_sheets Goals_conceded Saves_held Saves_parried Saves_tipped Shots_on_target_faced Expected_goals_prevented".split()))
LABELS={k:v.replace('_',' ') for k,v in LABELS.items()}
LABELS.update(identity_key="Player ID",player_name="Player",period="Season",kind="Competition type",club_name="Club",team_slot="Squad slot",appearances="Appearances",average_rating="Average rating",as_of="Observed through",oldest_observation="Earliest observation",newest_observation="Latest observation",players="Player count",competition_key="Competition",own_club_name="Represented club",retained_appearances="Retained appearance records",detailed_appearances="With valid detail",pass_completion_percent="Pass completion %",tackle_completion_percent="Tackle success %",shots_on_target_percent="Shots on target %",date="Date",opponent_club_name="Opponent",has_stats="Detail retained",stats_in_range="Range checks passed",attribution="Club attribution checked",home_club_name="Home team",away_club_name="Away team",home_goals="Home goals",away_goals="Away goals",played="Played",stadium_name="Stadium",home_team_slot="Home squad slot",away_team_slot="Away squad slot",wage_weekly="Weekly wage (base currency)",transfer_value="Value (base currency)",transfer_value_state="Value status",membership="Membership",loan_start="Loan start",loan_end="Loan end",contract_club_name="Contract club",contract_start="Contract start",type_name="Injury name",cause="Cause",severity="Severity",start="Start",end="End",wage="Weekly wage (base currency)",has_terms="Retained contract clauses",rating="Rating",left_at_minute="Minute left pitch",type_id="Injury type ID")
for key in list(LABELS): LABELS[key+'_per_90']=LABELS[key]+" /90 min"
for key in ('minutes','goals','assists','passes_attempted','passes_completed'): LABELS[key+'_coverage']=LABELS[key]+"Non-missing records"
MEMBERSHIP={'registered':"Registered here",'loan_out':"On loan",'historical_link':"Historical link"}


@st.cache_data(show_spinner=False)
def cached_data(stamp):
    return datasets()


def load_data(through_date):
    from src.archive import DB
    return [s for s in cached_data(DB.stat().st_mtime_ns) if s['snapshot']['date']<=through_date]


def competition_labels(data):
    path=ROOT/'data/manual/competition_names.json'
    manual=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    labels={}
    for snap in data:
        for c in snap['competitions']:
            labels[c['competition_key']]=manual.get(c['competition_key']) or c['name'] or ("Competition ID "+c['competition_key'])
    return labels


def show_table(rows,key,labels=None):
    if not rows:
        st.info("No retained records in this scope.")
        return
    frame=pd.DataFrame(rows)
    if 'kind' in frame: frame['kind']=frame['kind'].map(lambda v:KIND_NAMES.get(v,v))
    if 'membership' in frame: frame['membership']=frame['membership'].map(MEMBERSHIP)
    if labels and 'competition_key' in frame: frame['competition_key']=frame['competition_key'].map(lambda v:labels.get(v,v))
    frame=frame.rename(columns=LABELS)
    st.dataframe(frame,hide_index=True,width='stretch',height=min(550,max(140,len(frame)*35+40)))
    st.download_button("Download table CSV",frame.to_csv(index=False).encode('utf-8-sig'),key+'.csv','text/csv',key='download_'+key)


def finances(snap,identity=None):
    return [{**{k:p[k] for k in ('membership','wage_weekly','transfer_value','transfer_value_state','loan_start','loan_end','contract_club_name','contract_start')},
             'player_name':p['player']['name'],'club_name':p['player']['club_name'],"Contract expiry":p['player']['contract_end']}
            for p in snap['players'] if (identity is not None and p['player']['identity_key']==identity) or (identity is None and p['membership']!='historical_link')]


def person_panel(data,identity):
    if not data: return
    st.caption("Wages and values use the save's base currency, which is unverified. Loan wages are not necessarily Leicester's share.")
    show_table(finances(data[-1],identity),'person_money')
    with st.expander("Wage, value and loan snapshots"):
        show_table([{"Save date":d['snapshot']['date'],**r} for d in data for r in finances(d,identity)],'person_money_history')
    stats=[r for r in season_rows(data) if r['identity_key']==identity]
    out=aggregate_seasons(stats,('period','kind','club_name'))
    show_table(out,'person_seasons')
    st.caption("Season totals already include competition components. Do not add them again. Missing seasons are not filled with zeros.")
    with st.expander("Match history"):
        rows=[r for r in match_rows(data) if r['identity_key']==identity]
        show_table([{k:v for k,v in r.items() if k not in ('identity_key','player_uid','competition_id','opponent_team_id','opponent_club_uid','own_club_uid')} for r in rows],'person_matches',competition_labels(data))
    with st.expander("Injury and contract history"):
        injuries=latest_rows(data,'injuries',('identity_key','player_uid','kind','date','team_id','type_id'))
        show_table([{k:r[k] for k in ('kind','date','type_name','type_id','cause','severity','club_name','as_of')} for r in injuries if r['identity_key']==identity],'person_injuries')
        st.caption("history dates are injury occurrences; typed dates are expected returns. Both can refer to the same injury and must not be counted twice. Injury names are currently unavailable.")
        contracts=latest_rows(data,'contracts',('identity_key','club_uid','start','end'))
        show_table([{k:r[k] for k in ('club_name','start','end','wage','has_terms','as_of')} for r in contracts if r['identity_key']==identity],'person_contracts')


def render(data,club_uid):
    st.subheader("Season, competition and player data")
    if not data:
        st.info("No extended statistics at this date.")
        return
    st.caption("Cut off at the selected snapshot date. Repeated cumulative snapshots use the latest record; missing is not zero.")
    labels=competition_labels(data)
    stats=season_rows(data); matches=match_rows(data); fixtures=fixture_rows(data)
    details, competitions, money, medical, coverage=st.tabs(["Detailed season statistics","Competitions and matches","Wages, values and loans","Injuries and history","Season coverage"])
    with details:
        mode=st.radio("Aggregation scope",["Single season","Archived seasons combined"],horizontal=True)
        a,b,c=st.columns(3)
        period=a.selectbox("Season",sorted({r['period'] for r in stats},reverse=True),disabled=mode=="Archived seasons combined")
        eligible=[r for r in stats if ('/' in r['period'] if mode=="Archived seasons combined" else r['period']==period)]
        kinds=[k for k in KIND_NAMES if any(r['kind']==k for r in eligible)]
        kind=b.selectbox("Competition category",kinds,format_func=lambda k:KIND_NAMES[k])
        scope=c.selectbox("Statistics scope",["Leicester first team","All Leicester squads","All archived players (including loans)"])
        rows=[r for r in eligible if r['kind']==kind
              and (scope.startswith("All") or (r['club_uid']==club_uid and (scope.endswith("All squads") or r['team_slot']==0)))]
        query=st.text_input("Search statistics by player")
        rows=[r for r in rows if query.casefold() in (r['player_name'] or '').casefold()]
        grouping=('identity_key','player_name','period','kind','club_name','team_slot') if mode!="Archived seasons combined" else ('identity_key','player_name','kind','club_name','team_slot')
        aggregate=aggregate_seasons(rows,grouping)
        if mode=="Archived seasons combined": st.warning("Only archived seasons with detailed statistics are included; this is not a full career total.")
        all_columns=st.checkbox("Show all detailed and per-90 metrics")
        short=('player_name','appearances','goals','assists','shots','dribbles','key_passes','tackles_completed','distance_km','minutes','starts','substitute_appearances','shots_on_target','average_rating','period','kind','club_name','team_slot','newest_observation')
        display=[]
        for r in aggregate:
            row={k:r[k] for k in short if k in r}
            if all_columns: row.update({k:v for k,v in r.items() if k not in ('identity_key','players') and k not in row})
            display.append(row)
        from src.presentation import e
        leaders=[]
        for field,label in [('goals',"Most goals"),('assists',"Most assists"),('appearances',"Most appearances")]:
            candidates=[r for r in aggregate if r.get(field) is not None]
            if candidates:
                leader=max(candidates,key=lambda r:r[field])
                leaders.append((label,leader['player_name'],leader[field]))
        if leaders:
            for col,(label,name,value) in zip(st.columns(len(leaders)),leaders):
                with col:
                    st.html(f'<section class="attribute-panel"><div class="eyebrow">{e(label)} · Current filters</div><div class="player-name">{e(name)}</div><div class="profile-name elite">{e(value)}</div></section>')
        show_table(display,'season_players')
        st.caption("Statistics are grouped by competition type. Cumulative figures end at the displayed observation date, which may precede season end. This source cannot split separate domestic cups.")
        with st.expander("Selected player contributions (appearances count player entries)"):
            show_table(aggregate_seasons(rows),'season_contributions')
            st.caption("These are archived player contributions, not necessarily complete team totals or numbers of team matches.")
    with competitions:
        a,b=st.columns(2)
        period=a.selectbox("Match season",sorted({r['period'] for r in fixtures if r['period']}|{r['period'] for r in matches},reverse=True))
        scope=b.selectbox("Match club scope",["Leicester first team","All Leicester squads","All retained clubs (including loans)","Player club attribution unverified"])
        fr=[f for f in fixtures if f['period']==period and (scope.startswith("All") or
           ((f['home_club_uid']==club_uid and (scope.endswith("All squads") or f['home_team_slot']==0)) or (f['away_club_uid']==club_uid and (scope.endswith("All squads") or f['away_team_slot']==0))))]
        mr=[r for r in matches if r['period']==period and (r['own_club_uid'] is None if scope.endswith("Unverified") else r['own_club_uid'] is not None if scope.startswith("All") else r['own_club_uid']==club_uid and (scope.endswith("All squads") or r['own_team_slot']==0))]
        keys=sorted({r['competition_key'] for r in fr+mr})
        competition=st.selectbox("Specific competition",["All"]+keys,format_func=lambda k:labels.get(k,k))
        if competition!="All": fr=[r for r in fr if r['competition_key']==competition];mr=[r for r in mr if r['competition_key']==competition]
        st.caption("Competition IDs remain separate. Unverified names are not guessed. Match records may only contain appearances and scores; detailed shooting, dribbling and distance fields are unavailable per match.")
        st.markdown("**Player totals by competition**")
        show_table([{k:v for k,v in r.items() if k!='identity_key'} for r in aggregate_matches(mr,('player_name','identity_key','period','competition_key','own_club_name'))],'competition_players',labels)
        st.caption("Only retained match data passing range checks are totaled. Non-missing record counts show coverage. These are not complete season totals; minutes, assists, passing and ratings need in-game verification.")
        st.markdown("**Team fixtures and scores**")
        if not scope.endswith("Unverified"):
            show_table(aggregate_fixtures(fr,club_uid),'fixture_totals',labels)
            st.caption("Results use retained scores. Penalty shootout progression is not parsed, so trophies or qualification cannot be inferred.")
        show_table([{k:r[k] for k in ('date','competition_key','home_club_name','away_club_name','home_team_slot','away_team_slot','home_goals','away_goals','played','stadium_name')} for r in sorted(fr,key=lambda r:r['date'] or '')],'fixtures',labels)
        with st.expander("Expand individual match records"):
            show_table([{k:r[k] for k in ('player_name','date','competition_key','own_club_name','opponent_club_name','minutes','goals','assists','rating','passes_attempted','passes_completed','has_stats','stats_in_range','attribution')} for r in mr],'matches',labels)
    with money:
        st.caption("Wages and values use the unverified save base currency. Loan club and dates are shown; wages are not verified cost shares.")
        only=st.checkbox("Only players on loan")
        rows=finances(data[-1])
        show_table([r for r in rows if not only or r['membership']=='loan_out'],'finances')
    with medical:
        st.warning("Injury names could not be read. Validated dates and type IDs are retained. History is the save's retained window, not an entire career.")
        q=st.text_input("Search injuries and history by player")
        injuries=latest_rows(data,'injuries',('identity_key','player_uid','kind','date','team_id','type_id'))
        rows=[r for r in injuries if q.casefold() in (r['player_name'] or '').casefold()]
        show_table([{k:r[k] for k in ('player_name','kind','date','type_name','type_id','cause','severity','club_name','as_of')} for r in rows],'injuries')
        st.caption("history: occurrence date; typed: expected return date. These are not two injuries. Missing days out are not inferred.")
        contracts=latest_rows(data,'contracts',('identity_key','club_uid','start','end'))
        show_table([{k:r[k] for k in ('player_name','club_name','start','end','wage','has_terms','as_of')} for r in contracts if q.casefold() in (r['player_name'] or '').casefold()],'contracts')
        st.caption("Contract chains can contain past, current and agreed future contracts. They are not complete transfer history; no fees are inferred.")
    with coverage:
        years=range(2026,int(data[-1]['snapshot']['date'][:4])+1)
        rows=[]
        for y in years:
            p=f'{y}/{str(y+1)[-2:]}'
            f=[r for r in fixtures if r['period']==p and ((r['home_club_uid']==club_uid and r['home_team_slot']==0) or (r['away_club_uid']==club_uid and r['away_team_slot']==0))]
            m=[r for r in matches if r['period']==p and r['own_club_uid']==club_uid and r['own_team_slot']==0]
            s=[r for r in stats if r['period']==p and r['club_uid']==club_uid and r['team_slot']==0]
            rows.append({"Season":p,"Retained played fixtures":sum(bool(r['played']) for r in f),"Player appearance records":len(m),"With valid detail":sum(bool(r['has_stats'] and r['stats_in_range']) for r in m),"Detailed statistics observed through":max((r['as_of'] for r in s),default="Missing"),"Completeness":"Full match coverage not established"})
        show_table(rows,'coverage')
        st.info("Only retained saves can recover history. End-of-season saves are especially useful. New imports preserve old snapshots. English seasons use a July boundary; calendar-year loan leagues require date checks.")
        show_table([{"Save date":d['snapshot']['date'],"Registered players":sum(p['membership']=='registered' for p in d['players']),"Players on loan":sum(p['membership']=='loan_out' for p in d['players']),"Season statistic rows":len(d['season_stats']),"Match record rows":len(d['matches']),"Injury record rows":len(d['injuries'])} for d in data],'snapshots_coverage')
