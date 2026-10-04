"""Durable chat jobs, independent of browser refresh; reuse existing tools/auth/gate."""
import json,threading,time,uuid,re
from datetime import datetime,timezone
from contextlib import closing
from src import chat_store as store,chat_auth as auth
from src.archive import snapshots,squad
from src.chat_tools import ArchiveTools,TOOLS,AGENT_INSTRUCTIONS,LABELS
from src.evidence_gate import INSTRUCTIONS,validate_answer
from src.chat_routing import unsupported_request
from src.lore import load_lore
from src.i18n import translate
LOCK=threading.RLock()
CATALOG={}

def init():
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS web_jobs(id TEXT PRIMARY KEY,chat_id TEXT,assistant_id TEXT,state TEXT,config TEXT,created TEXT,error TEXT)')
        pending=c.execute("SELECT id,assistant_id FROM web_jobs WHERE state='running'").fetchall()
        for row in pending:
            c.execute("UPDATE messages SET text=?,status='incomplete' WHERE id=?",("The service restarted and interrupted this response. Saved execution records remain available; no automatic retry occurred.",row['assistant_id']))
        c.execute("UPDATE web_jobs SET state='interrupted',error='Service restarted' WHERE state='running'")

def catalog(cid,refresh=False):
    with LOCK:
        if refresh or cid not in CATALOG or time.time()-CATALOG[cid][0]>600:
            CATALOG[cid]=(time.time(),auth.models(cid))
        return CATALOG[cid][1]

def jobs(room):
    with store.connect() as c:
        return [dict(r) for r in c.execute('SELECT id,assistant_id,state,error,created FROM web_jobs WHERE chat_id=? ORDER BY created DESC LIMIT 1',(room,))]

def submit(a):
    request_id=a.get('request_id','')
    if not re.fullmatch('[a-zA-Z0-9-]{16,80}',request_id):raise ValueError("Invalid request identifier. Refresh and retry.")
    with LOCK:
        with store.connect() as c:
            existing=c.execute('SELECT id,state,assistant_id FROM web_jobs WHERE id=?',(request_id,)).fetchone()
            if existing:return dict(existing)
            active=c.execute("SELECT id FROM web_jobs WHERE state='running'").fetchone()
            if active:raise ValueError("A reply is already running. Wait for completion; navigation will not interrupt it.")
        room=next((x for x in store.chats() if x['id']==a.get('chat_id')),None)
        if not room:raise ValueError("Chat not found.")
        question=str(a.get('question','')).strip()
        hist=store.messages(room['id'])
        if a.get('retry'):
            question=next((m['text'] for m in reversed(hist) if m['role']=='user'),'')
        if not question or len(question)>10000:raise ValueError("Enter a question of at most 10,000 characters.")
        snapshot=next((s for s in snapshots() if s['id']==a.get('snapshot_id')),None)
        if not snapshot:raise ValueError("Select a valid snapshot.")
        period=a.get('season','')
        if not re.fullmatch(r'\d{4}/\d{2}',period):raise ValueError("Use a season such as 2035/36.")
        kind=a.get('kind','overall');scope=a.get('scope','first_team')
        if kind not in ('overall','league','cup','continental','non_competitive','international') or scope not in ('first_team','club','all'):raise ValueError("Invalid query scope.")
        cid=a.get('account');model=a.get('model');local=unsupported_request(question)
        if not local:
            options,_=auth.account_options()
            if cid not in options:raise ValueError("Select a signed-in account first.")
            if model not in {m['slug'] for m in catalog(cid)}:raise ValueError("The selected model is unavailable. Refresh the model list.")
        chosen=a.get('people',[])
        if not isinstance(chosen,list) or len(chosen)>50 or any(not isinstance(x,str) for x in chosen):raise ValueError("Invalid character selection.")
        cfg=dict(language='zh-CN' if a.get('language')=='zh-CN' else 'en',snapshot=snapshot,season=period,kind=kind,scope=scope,account=cid,model=model,mode=room['mode'],people=chosen,require_lookup=bool(a.get('require_lookup',True)),question=question)
        # One transaction reserves the job and both messages; concurrent/repeated submits cannot duplicate spend.
        mid=uuid.uuid4().hex;now=datetime.now(timezone.utc).isoformat()
        with store.connect() as c:
            if not a.get('retry'):c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,room['id'],'user',question,'complete','',now))
            c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(mid,room['id'],'assistant',"Generating; execution records are being saved.",'incomplete',model or 'local',datetime.now(timezone.utc).isoformat()))
            c.execute('INSERT INTO web_jobs VALUES(?,?,?,?,?,?,?)',(request_id,room['id'],mid,'running',json.dumps(cfg,ensure_ascii=False),now,None))
        if model:store.remember_model(room['id'],room['mode'],model)
        threading.Thread(target=run,args=(request_id,room['id'],mid,cfg,local),daemon=True).start()
        return dict(id=request_id,state='running',assistant_id=mid)

REPAIR_INSTRUCTIONS="Your previous structured answer failed the evidence check. Return only the complete corrected JSON object. Fix every listed reference: query is the tool result's query_index, list positions are the record's row_index, and value is copied exactly from the tool result. If a statement cannot be supported by the tool results, remove its reference and soften or remove the statement. Do not invent values. No tools are available in this request.\n"


def repair_answer(cfg,draft,verdict,queries,events,event,language_line):
    """One tool-free attempt to fix a failed structured answer against the same evidence; returns (draft, verdict)."""
    evidence=json.dumps([dict(query_index=i,name=q['name'],arguments=q['arguments'],result=q['result']) for i,q in enumerate(queries)],ensure_ascii=False,separators=(',',':'))
    if len(evidence)>350000:
        event(dict(kind='evidence_repair',title="Repair skipped: evidence too large to resend",details=dict(errors=verdict['errors'],evidence_characters=len(evidence))))
        return draft,verdict
    event(dict(kind='evidence_repair',title="Sending evidence errors back for one repair attempt",details=dict(
        errors=verdict['errors'],previous_draft=draft,evidence_characters=len(evidence),
        note="One tool-free model request with the same tool results. The corrected answer is checked again; it is not published unless it passes.")))
    offset=sum(e.get('kind')=='model_request' for e in events)
    def shifted(e):
        d=e.get('details') or {}
        event({**e,'details':{**d,'round':d['round']+offset,'phase':'repair'}} if 'round' in d else e)
    inputs=[dict(role='user',content=cfg['question']),
            dict(role='user',content='Tool results by query_index:\n'+evidence),
            dict(role='assistant',content=draft),
            dict(role='user',content='Evidence check errors:\n'+'\n'.join('- '+e for e in verdict['errors']))]
    try:repaired=''.join(auth.stream_reply(cfg['account'],cfg['model'],inputs,REPAIR_INSTRUCTIONS+INSTRUCTIONS+language_line,on_event=shifted,final_text_only=True))
    except auth.ConnectionFailure as exc:
        event(dict(kind='error',title="Repair attempt incomplete",details=dict(message=str(exc))))
        return draft,verdict
    result=validate_answer(repaired,queries,cfg['snapshot']['game_date'],cfg['question'])
    event(dict(kind='evidence_recheck',title="Evidence check after repair",details={k:v for k,v in result.items() if k!='text'}))
    return repaired,result


def run(jid,room,mid,cfg,local=None):
    events=[];queries=[];start=time.monotonic();raw='';state='failed';text="This response did not complete.";draft=None
    def event(e):
        name=(e.get('details') or {}).get('name')
        if e.get('kind') in ('tool_requested','tool_result') and name in LABELS:e={**e,'details':{**e['details'],'label':LABELS[name]}}
        events.append({**e,'elapsed_seconds':round(time.monotonic()-start,2)})
        store.save_workflow(mid,events)
    def query(q):
        queries.append(q);store.save_queries(mid,queries)
    try:
        event(dict(kind='input',title="Background job started",details=dict(question=cfg['question'],snapshot_date=cfg['snapshot']['game_date'],discussion_season=cfg['season'],model=cfg['model'],require_lookup=cfg['require_lookup'],background_job=True)))
        if local:
            text=translate(local['answer'],cfg.get('language','en'));state='complete';event(dict(kind='request_routing',title="Request scope check",details=dict(reason=local['reason'],model_called=False)))
        else:
            tool=ArchiveTools(cfg['snapshot'],on_event=event)
            with closing(tool._connect()) as c:data=tool._data(c)
            people=[p for p in squad(cfg['snapshot']['id']) if p['identity_key'] in cfg['people']]
            lore=load_lore()
            if cfg['mode']=='analysis':lore=[r for r in lore if r['level']=='canon']
            background=store.lookup_context(people,lore,data,cfg['snapshot'],cfg['season'],cfg['kind'],cfg['scope'],question=cfg['question'])
            memory=json.loads(background).get('conversation_memory',{})
            event(dict(kind='memory_context',title='Relevant conversation memory loaded',details=dict(
                source_sha256=memory.get('source_sha256'),excerpts=memory.get('rows',[]),
                note='Automatic context retrieval, not a model-requested tool call. Original conversation is not verified FM evidence. More context is available through story_memory.')))
            history=[dict(role=m['role'],content=m['text']) for m in store.messages(room) if m['status']=='complete'][-20:]
            # Drop whole oldest messages when oversized; preserve current question and original DB history.
            removed=0
            while len(history)>1 and sum(len(m['content']) for m in history)>60000:
                history.pop(0);removed+=1
            if removed:event(dict(kind='context_window',title="Limiting conversation context",details=dict(omitted_messages=removed,note="Only this request's context is shortened; original history is preserved.")))
            if len(background)>120000:raise ValueError("Character or story background is too long. Select fewer characters and retry.")
            gated=cfg['mode']=='analysis' or cfg['require_lookup']
            instructions=store.instructions_for(cfg['mode'])+AGENT_INSTRUCTIONS+(INSTRUCTIONS if gated else '')+"\nQuoted archive context:\n"+background
            language_line='\nResponse language: '+('Simplified Chinese' if cfg.get('language')=='zh-CN' else 'English')+'. Keep JSON keys and evidence paths unchanged. Follow explicit user requests for another response language.'
            instructions+=language_line
            last_flush=0
            for delta in auth.stream_reply(cfg['account'],cfg['model'],history,instructions,tools=TOOLS,execute_tool=tool.execute,on_tool=query,on_event=event,require_lookup=cfg['require_lookup'],final_text_only=gated):
                raw+=delta
                if not gated and time.monotonic()-last_flush>1:
                    with store.connect() as c:c.execute('UPDATE messages SET text=? WHERE id=?',(raw,mid))
                    last_flush=time.monotonic()
            if gated:
                draft=raw
                verdict=validate_answer(raw,queries,cfg['snapshot']['game_date'],cfg['question'])
                event(dict(kind='evidence_check',title="Pre-answer evidence check",details={k:v for k,v in verdict.items() if k!='text'}))
                if not verdict['passed'] and verdict.get('repairable') and queries:
                    draft,verdict=repair_answer(cfg,draft,verdict,queries,events,event,language_line)
                text=translate(verdict['text'],cfg.get('language','en'));state='complete' if verdict['passed'] else 'failed'
            else:text=raw;state='complete' if raw.strip() else 'failed'
    except (auth.ConnectionFailure,ValueError) as exc:
        text="Response incomplete: "+str(exc)
        event(dict(kind='error',title="Generation incomplete",details=dict(message=str(exc))))
    except Exception as exc:
        text="Local background processing failed. Execution records are saved. No automatic retry occurred."
        event(dict(kind='error',title="Local processing failed",details=dict(error_type=type(exc).__name__)))
    finally:
        store.save_queries(mid,queries);store.save_workflow(mid,events,validation_draft=draft)
        with store.connect() as c:
            c.execute('UPDATE messages SET text=?,status=? WHERE id=?',(text,'complete' if state=='complete' else 'incomplete',mid))
            c.execute('UPDATE web_jobs SET state=?,error=? WHERE id=?',(state,None if state=='complete' else text,jid))
