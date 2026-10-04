import json
from contextlib import closing
import pandas as pd
from src.i18n import st
from src.archive import DB
from src.league_archive import connection, read_teams
from src.analytics_ui import LABELS
from src.analytics import KIND_NAMES


def render():
    st.subheader("Premier League snapshots")
    st.caption("Select a season independently of the sidebar snapshot. Teams are tracked continuously; the current season uses the latest whole snapshot, older seasons freeze on rollover. Contracts and injuries are not read here.")
    with closing(connection()) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='league_snapshots'").fetchone():
            st.info("No Premier League snapshots imported.");return
        periods=[r[0] for r in con.execute('SELECT DISTINCT season FROM league_snapshots ORDER BY season DESC')]
        if not periods:st.info("Premier League saves are being checked; none have completed import yet.");return
        period=st.selectbox("Team snapshot season",periods)
        frozen=con.execute('SELECT * FROM league_frozen_seasons WHERE season=?',(period,)).fetchone()
        count=con.execute('SELECT COUNT(*) FROM league_snapshots WHERE season=?',(period,)).fetchone()[0]
    teams=read_teams(period)
    if not teams:st.info("No readable snapshot for this season.");return
    if frozen:
        st.info(f"Frozen · {frozen['as_of']} · {frozen['note']}")
    else:
        st.success(f"Updating · Latest save {teams[0]['game_date']} · Retained {count} team snapshots")
    st.caption("Promoted clubs are added and relegated tracked clubs are retained. Their league statistics do not enter Premier League comparisons. Rosters are stored with team snapshots, without individual historical tracking. Team statistics may include players who left or moved squads.")
    premier=st.checkbox("Only this season's Premier League clubs",value=True)
    visible=[t for t in teams if not premier or t['in_premier']]
    rows=[]
    for t in visible:
        standing=t['standing'] or {}
        rows.append({"Club":t['club_name'],"In Premier League this season":bool(t['in_premier']),"Observed through":t['game_date'],
            "Position":standing.get('position'),"Played":standing.get('played'),"Points":standing.get('points'),
            "Goals":standing.get('goals_for'),"Goals conceded":standing.get('goals_against'),
            "First-team size":len(t['roster']),"Players with league statistics":t['coverage']['league_player_count']})
    st.dataframe(pd.DataFrame(rows).sort_values("Position",na_position='last'),hide_index=True,width='stretch')
    club=st.selectbox("View club",[t['club_uid'] for t in visible],format_func=lambda uid:next(t['club_name'] for t in visible if t['club_uid']==uid))
    team=next(t for t in visible if t['club_uid']==club)
    tab_stats,tab_roster,tab_coverage=st.tabs(["Detailed match statistics","First-team roster and visible attributes","Coverage and archive rules"])
    with tab_stats:
        kinds=list(team['coverage']['stats_by_kind'])
        if kinds:
            kind=st.selectbox("Club competition type",kinds,index=kinds.index('league') if 'league' in kinds else 0,format_func=lambda k:KIND_NAMES.get(k,k))
            stats=[r for r in team['stats'] if r['kind']==kind]
            frame=pd.DataFrame(stats).rename(columns=LABELS)
            st.dataframe(frame,hide_index=True,width='stretch')
            st.download_button("Download club statistics CSV",frame.to_csv(index=False).encode('utf-8-sig'),file_name=f'club-{club}-{period.replace("/","-")}-{kind}.csv',mime='text/csv')
        else:st.info("No statistics for this season in the snapshot. Missing records do not mean every metric is zero.")
    with tab_roster:
        st.dataframe([{"Name":p['name'],"Age":p['age'],"Height":p['height_cm'],"Position":' / '.join(p['natural_positions']),**p['attributes']} for p in team['roster']],hide_index=True,width='stretch')
    with tab_coverage:
        st.json(team['coverage'])
        st.caption("Use one whole-team snapshot, never add saves. Reconcile the season using fixtures and standings. A new season or post-season statistics reset freezes the previous season's last valid snapshot. Without an end-of-season save coverage is partial; 38 league matches do not prove cups have finished.")
        st.caption("The database workbench exposes league_snapshots, league_team_snapshots, league_frozen_seasons, v_league_team_season and v_league_player_stats.")
