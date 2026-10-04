"""Screenshot-backed transfers. Financial figures are displayed amounts, not settled fees."""
import hashlib
import json
from datetime import date
from pathlib import Path
from src.archive import DB, connect
from src.safe_export import ROOT

BATCHES=ROOT/'data/manual/transfers'

def transfer_season(day):
    day=date.fromisoformat(day)
    year=day.year if day.month>=6 else day.year-1
    return f'{year}/{str(year+1)[-2:]}'

def event_id(row):
    key=[row[k] for k in ('date','direction','player_name','other_club')]
    return hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()

def import_batch(path,db=DB):
    batch=json.loads(Path(path).read_text(encoding='utf-8'))
    assert batch['schema_version']==1
    rows=[]
    for r in batch['transfers']:
        assert set(r)=={'date','direction','player_name','other_club','fee_display','fee_eur_displayed','kind','source_group','source_images','note'}
        date.fromisoformat(r['date'])
        assert r['direction'] in ('in','out') and r['kind'] in ('transfer','loan')
        assert r['fee_eur_displayed'] is None or (type(r['fee_eur_displayed']) is int and r['fee_eur_displayed']>=0)
        assert r['source_images'] and all(i in batch['images'] for i in r['source_images'])
        assert r['source_group'] in batch['groups']
        rows.append({**r,'season':transfer_season(r['date']),'evidence_level':'canon','source_type':'user_game_screenshot','season_basis':'user_rule_june_1'})
    with connect(db) as con:
        con.executescript('''CREATE TABLE IF NOT EXISTS transfer_batches(id TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transfer_events(id TEXT PRIMARY KEY,date TEXT NOT NULL,season TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transfer_evidence(event_id TEXT NOT NULL,batch_id TEXT NOT NULL,images_json TEXT NOT NULL,PRIMARY KEY(event_id,batch_id));''')
        with con:
            previous=con.execute('SELECT payload_json FROM transfer_batches WHERE id=?',(batch['id'],)).fetchone()
            serialized=json.dumps(batch,ensure_ascii=False)
            if previous and previous[0]!=serialized: raise ValueError('Existing batch changed; review before replacing')
            con.execute('INSERT OR IGNORE INTO transfer_batches VALUES(?,?)',(batch['id'],serialized))
            added=0
            for r in rows:
                key=event_id(r)
                prev=con.execute('SELECT payload_json FROM transfer_events WHERE id=?',(key,)).fetchone()
                if prev:
                    old=json.loads(prev[0])
                    if any(old[k]!=r[k] for k in ('fee_display','fee_eur_displayed','kind')): raise ValueError('Conflicting transfer evidence; review required')
                else:
                    con.execute('INSERT INTO transfer_events VALUES(?,?,?,?)',(key,r['date'],r['season'],json.dumps(r,ensure_ascii=False)))
                    added+=1
                con.execute('INSERT OR IGNORE INTO transfer_evidence VALUES(?,?,?)',(key,batch['id'],json.dumps(r['source_images'])))
    return added

def read_transfers(db=DB):
    with connect(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='transfer_events'").fetchone(): return [],[]
        rows=[json.loads(r[0]) for r in con.execute('SELECT payload_json FROM transfer_events ORDER BY date, id')]
        batches=[json.loads(r[0]) for r in con.execute('SELECT payload_json FROM transfer_batches ORDER BY id')]
    return rows,batches

def render():
    from src.i18n import st
    import pandas as pd
    from src.presentation import transfer_board
    rows,batches=read_transfers()
    st.caption("Club transfer history · seasons start June 1 · all archived dates")
    if not rows:
        st.info("No transfer screenshots imported.");return
    a,b,c=st.columns(3)
    season=a.selectbox("Transfer season",["All"]+sorted({r['season'] for r in rows}))
    direction=b.selectbox("Transfer direction",["All","In","Out"])
    query=c.text_input("Search transfer player")
    filtered=[r for r in rows if (season=="All" or r['season']==season) and (direction=="All" or r['direction']=={"In":'in',"Out":'out'}[direction]) and query.casefold() in r['player_name'].casefold()]
    a,b,c=st.columns(3)
    a.metric("Imported events",len(filtered))
    a.caption("Only transfers actually visible in supplied screenshots are recorded.")
    for col,d,label in [(b,'in',"Known incoming displayed fees"),(c,'out',"Known outgoing displayed fees")]:
        subset=[r for r in filtered if r['direction']==d]
        total=sum(r['fee_eur_displayed'] for r in subset if r['fee_eur_displayed'] is not None)
        col.metric(label,f'€{total:,.0f}')
        col.caption(f"Unknown fees: {sum(r['fee_eur_displayed'] is None for r in subset)} events")
    st.caption("Amounts are transcribed from screenshots and may be rounded, not exact cash receipts or paid installments. Unspecified loan fees are unknown, not €0.")
    display=[{"Season":r['season'],"Date":r['date'],"Direction":"In" if r['direction']=='in' else "Out","Player":r['player_name'],"Other club / source":r['other_club'],"Type":"Loan" if r['kind']=='loan' else "Transfer","Displayed fee":r['fee_display'],"Evidence":"Game screenshot · canon","Source screenshot":', '.join(r['source_images']),"Notes":r['note']} for r in filtered]
    frame=pd.DataFrame(display)
    if not filtered:st.info("No transfers match these filters.")
    transfer_board(filtered,'in')
    transfer_board(filtered,'out')
    with st.expander("Sources and notes / table view"):
        st.dataframe(frame,hide_index=True,width='stretch',height=400)
    st.download_button("Download transfers CSV",frame.to_csv(index=False).encode('utf-8-sig'),'transfers.csv','text/csv')
    with st.expander("View original screenshot"):
        images={k:v for b in batches for k,v in b['images'].items()}
        choice=st.selectbox("Evidence screenshot",list(images))
        st.image(str(ROOT/images[choice]['path']))
