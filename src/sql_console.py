"""Local read-only SQL workbench over archive data and temporary convenience views."""
import csv
import io
import sqlite3
import time
from contextlib import closing
from src.i18n import st
from src.archive import DB
from src.analytics import COUNTS


def connect(db=DB):
    con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    metrics=','.join(f"json_extract(j.value,'$.{field}') AS {field}" for field in COUNTS)
    con.executescript(f"""
        CREATE TEMP VIEW v_season_stats AS
        SELECT a.game_date AS observation_date,
        json_extract(j.value,'$.identity_key') AS identity_key,
        json_extract(j.value,'$.player_name') AS player_name,
        json_extract(j.value,'$.period') AS season,
        json_extract(j.value,'$.kind') AS kind,
        json_extract(j.value,'$.team_id') AS team_id,
        json_extract(j.value,'$.club_name') AS club_name,
        json_extract(j.value,'$.team_slot') AS team_slot,
        json_extract(j.value,'$.average_rating') AS average_rating,
        {metrics}, a.sha256 AS snapshot_hash
        FROM analytics_snapshots a, json_each(a.payload_json,'$.season_stats') j;
        CREATE TEMP VIEW v_season_latest AS
        SELECT * FROM (SELECT *, ROW_NUMBER() OVER (
          PARTITION BY identity_key,season,kind,team_id
          ORDER BY observation_date DESC,snapshot_hash DESC) AS observation_rank
          FROM v_season_stats) WHERE observation_rank=1;
        CREATE TEMP VIEW v_players AS
        SELECT s.game_date AS observation_date,p.identity_key,
        json_extract(p.visible_json,'$.name') AS player_name,
        json_extract(p.visible_json,'$.age') AS age,
        json_extract(p.visible_json,'$.club_name') AS club_name,
        json_extract(p.visible_json,'$.natural_positions') AS positions,
        json_extract(p.visible_json,'$.contract_end') AS contract_end
        FROM player_snapshots p JOIN snapshots s ON s.id=p.snapshot_id;
        CREATE TEMP VIEW v_transfers AS SELECT date,season,
        json_extract(payload_json,'$.player_name') AS player_name,
        json_extract(payload_json,'$.direction') AS direction,
        json_extract(payload_json,'$.other_club') AS other_club,
        json_extract(payload_json,'$.fee_eur_displayed') AS fee_eur_displayed,
        json_extract(payload_json,'$.kind') AS kind FROM transfer_events;
    """)
    con.execute('PRAGMA query_only=ON')
    return con


def schema(db=DB):
    with closing(connect(db)) as con:
        objects=con.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view') UNION ALL SELECT name,type,sql FROM sqlite_temp_master WHERE type='view' ORDER BY name").fetchall()
        return [dict(name=name,type=kind,sql=sql,columns=[dict(name=r[1],type=r[2] or "Determined by expression",nullable=not bool(r[3]),primary_key=bool(r[5])) for r in con.execute('PRAGMA table_info("'+name.replace('"','""')+'")')]) for name,kind,sql in objects]


def authorize(action,arg1,arg2,database,source):
    if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in ('load_extension','readfile','writefile'):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE) else sqlite3.SQLITE_DENY


def query(sql,db=DB,limit=500,seconds=3):
    if not sql.strip():raise ValueError("Enter one SELECT or WITH query.")
    started=time.monotonic()
    with closing(connect(db)) as con:
        con.set_authorizer(authorize)
        # Imported snapshot JSON can exceed 2 MB even when projecting a few scalars.
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,64_000_000)
        con.set_progress_handler(lambda: int(time.monotonic()-started>seconds),1000)
        cursor=con.execute(sql)
        columns=[d[0] for d in cursor.description or []]
        rows=[];size=0;truncated=False
        for row in cursor:
            values=[str(v) if isinstance(v,bytes) else v for v in row]
            size+=sum(len(str(v)) for v in values)
            if len(rows)>=limit or size>1_000_000:
                truncated=True;break
            rows.append(values)
        return dict(columns=columns,rows=rows,truncated=truncated,elapsed_ms=round((time.monotonic()-started)*1000,1))


EXAMPLES={
    "Season player statistics": "SELECT player_name, club_name, minutes, goals, assists, average_rating, observation_date\nFROM v_season_latest\nWHERE season = '2035/36' AND kind = 'overall' AND team_slot = 0\nORDER BY goals DESC;",
    "Compare Monga and Evans": "SELECT player_name, season, minutes, goals, assists, average_rating, observation_date\nFROM v_season_latest\nWHERE season = '2035/36' AND kind = 'overall'\n  AND (player_name LIKE '%Monga%' OR player_name LIKE '%Evans%');",
    "List snapshot dates": 'SELECT id, game_date, club_name FROM snapshots ORDER BY game_date DESC;',
    "View transfers": 'SELECT * FROM v_transfers ORDER BY date DESC LIMIT 100;',
    "Read players from raw JSON": "SELECT identity_key, json_extract(visible_json, '$.name') AS player_name\nFROM player_snapshots LIMIT 20;"
}


def render():
    st.subheader("Database workbench")
    st.caption("Local SQLite · read-only · no model calls or subscription usage. All imported dates are visible here; sidebar snapshot filters do not apply.")
    st.info("Table names, columns and JSON keys are English. Data values can contain multiple languages. Temporary v_ views in this workbench disappear on disconnect and do not alter stored data.")
    st.code(str(DB),language=None)
    structures=schema()
    left,right=st.columns([1,2])
    with left:
        selected=st.radio("Tables / query views",[s['name'] for s in structures],key='sql_schema_selection')
        item=next(s for s in structures if s['name']==selected)
        st.dataframe(item['columns'],hide_index=True,use_container_width=True)
        with st.expander("Table / view SQL"):st.code(item['sql'],language='sql')
        if st.button("Browse this table"):
            st.session_state.sql_editor=f'SELECT * FROM "{selected}" LIMIT 20;'
    with right:
        example=st.selectbox("Example query",list(EXAMPLES))
        if st.button("Load example"):st.session_state.sql_editor=EXAMPLES[example]
        if 'sql_editor' not in st.session_state:st.session_state.sql_editor=EXAMPLES["Season player statistics"]
        sql=st.text_area("SQL editor",key='sql_editor',height=230)
        st.caption("Run one SELECT / WITH statement. At most 500 rows and about three seconds. v_season_stats contains repeated cumulative snapshots; do not sum them. v_season_latest selects latest player/season/competition/club records, which can have different dates. Do not add totals and competition components.")
        if st.button("Run query",type='primary'):
            try:
                result=query(sql)
                st.session_state.sql_result=(sql,result)
            except (sqlite3.Error,ValueError) as exc:
                st.session_state.pop('sql_result',None)
                st.error(f'Query incomplete: {exc}. Only read-only queries are permitted. Reduce the scope and retry.')
        if 'sql_result' in st.session_state:
            executed,result=st.session_state.sql_result
            st.caption(f"Returned {len(result['rows'])} rows · {result['elapsed_ms']} ms")
            if executed!=sql:st.info("These are the previous query results. Run again after editing SQL.")
            if result['truncated']:st.warning("Result exceeds the row or size limit; only part is shown. Add filters or pagination.")
            import pandas as pd
            st.dataframe(pd.DataFrame(result['rows'],columns=result['columns']),hide_index=True,use_container_width=True)
            output=io.StringIO();writer=csv.writer(output);writer.writerow(result['columns']);writer.writerows(result['rows'])
            st.download_button("Download result CSV",output.getvalue().encode('utf-8-sig'),file_name='query-results.csv',mime='text/csv')
