import json
import time
from src.i18n import st, language
from src import chat_auth as auth
from src import chat_store as store
from src.transfers import read_transfers
from src.chat_tools import ArchiveTools,TOOLS,LABELS as TOOL_LABELS,AGENT_INSTRUCTIONS
from src.chat_trace import render_trace, render_usage

def render(players,lore,snapshot,analytics=None):
    mode=st.radio("Chat space",['story','analysis'],format_func=lambda m:"Dressing room · stories and headcanon" if m=='story' else "Analysis room · matches and transfers",horizontal=True,key='chat_space')
    st.caption("The two spaces save separate conversations and share archive data, not complete chat histories. Earlier chats remain in the dressing room.")
    st.caption("On-demand lookup is enabled. The model can query again for evidence; see records below each reply. Up to eight calls per response. More model rounds use more subscription allowance.")
    st.caption("DRESSING ROOM · conversations saved locally; you decide which stories to collect")
    st.info("Uses ChatGPT plan access through authorization. Messages and selected context are sent to OpenAI. This page does not use an API key or automatically switch to paid API access.")
    with st.expander("ChatGPT connection and account",expanded=True):
        try:options,active=auth.account_options()
        except auth.ConnectionFailure as exc:st.error(str(exc));return
        selected=st.selectbox("ChatGPT account",[None]+list(options),index=(list(options).index(active)+1 if active in options else 0),format_func=lambda cid:options.get(cid,"Add account / not signed in"))
        a,b=st.columns(2)
        if a.button("Prepare ChatGPT sign-in",type='primary'):
            old=st.session_state.pop('chat_login_attempt',None)
            if old and old.status=='waiting':old.status='cancelled'
            try:st.session_state.chat_login_attempt=auth.LoginAttempt(selected)
            except (OSError,auth.ConnectionFailure):st.error("The local login listener could not start. Please retry.")
        if selected and b.button("Sign out of this account"):
            confirmed=auth.sign_out(selected)
            st.session_state.pop('chat_model_catalog',None)
            st.session_state.pop('chat_model_attempt',None)
            st.session_state.pop('chat_model_error',None)
            st.session_state.logout_notice="Signed out." if confirmed else "Signed out locally; remote revocation was not confirmed. You can disconnect the app in ChatGPT settings."
            st.rerun()
        if st.session_state.get('logout_notice'):st.caption(st.session_state.pop('logout_notice'))
        pending=st.session_state.get('chat_login_attempt')
        if pending:
            st.caption(pending.message)
            if pending.status=='waiting':st.link_button('Continue with ChatGPT',pending.url)
            if st.button("Refresh login status"):
                if pending.status=='success':
                    st.session_state.pop('chat_login_attempt',None)
                    st.session_state.pop('chat_model_attempt',None)
                st.rerun()
        st.link_button("View ChatGPT usage and app authorization",'https://chatgpt.com/#settings/Usage')
    model=None
    choices={}
    model_problem="Select a signed-in account above, or finish ChatGPT sign-in."
    if selected:
        refresh=st.button("Load available models / refresh")
        catalog=st.session_state.get('chat_model_catalog')
        attempt=st.session_state.get('chat_model_attempt')
        if refresh or (not (catalog and catalog[0]==selected) and (attempt!=selected or not st.session_state.get('chat_model_error'))):
            st.session_state.chat_model_attempt=selected
            st.session_state.pop('chat_model_error',None)
            try:
                with st.spinner("Restoring available chat models…"):
                    st.session_state.chat_model_catalog=(selected,auth.models(selected))
            except auth.ConnectionFailure as exc:
                st.session_state.chat_model_error=str(exc)
            except (OSError,ValueError,TypeError):
                st.session_state.chat_model_error="Could not read the model directory. Retry; no chat request was sent."
        catalog=st.session_state.get('chat_model_catalog')
        model_problem=st.session_state.get('chat_model_error') or "No models loaded. Click Load available models / refresh above."
        if catalog and catalog[0]==selected:
            choices={m['slug']:m.get('display_name',m['slug']) for m in catalog[1]}
            if not choices:model_problem="The account returned no models for this application. Check plan authorization."
        if choices:
            st.success(f'Loaded {len(choices)} available models; select one under Chat model.')
            if st.session_state.get('chat_model_error'):st.warning("Refresh failed; keeping the last successful list."+st.session_state.chat_model_error)
        else:st.error("Model loading incomplete: "+model_problem)
    with st.expander("New chat"):
        title=st.text_input("Chat title",placeholder="For example Page and De Cat in 2031/32")
        if st.button("Create chat"):
            st.session_state['room_choice_'+mode]=store.create_chat(title,mode=mode);st.rerun()
    rooms=[r for r in store.chats() if r.get('mode','story')==mode]
    if not rooms:
        st.info("Create a chat first. You can create a topic before signing in, then authorize to start chatting.");return
    labels={r['id']:r['title'] for r in rooms}
    room=st.selectbox("Saved chats",list(labels),format_func=lambda k:labels[k],key='room_choice_'+mode)
    if choices:
        current=next(r for r in rooms if r['id']==room)
        preferred=current.get('model') or 'gpt-5.6-sol'
        model_options=list(choices)
        model=st.selectbox("Chat model",model_options,index=model_options.index(preferred) if preferred in model_options else 0,format_func=lambda k:choices[k],key='model_'+room)
        if current.get('model')!=model:store.remember_model(room,mode,model)
        st.caption("Models are remembered per chat. New chats prefer 5.6 Sol when available to the account.")
    names={p['identity_key']:p for p in players}
    a,b=st.columns([2,1])
    people=a.multiselect("Include character background",list(names),format_func=lambda k:names[k]['name'],key='people_'+room)
    from src.analytics import season as season_for_date, KIND_NAMES
    season=b.text_input("Discussion season",value=season_for_date(snapshot['game_date']),placeholder="For example 2031/32",key='season_'+room)
    a,b=st.columns(2)
    kind=a.selectbox("Default competition",['overall','league','cup','continental','non_competitive','international'],format_func=lambda k:KIND_NAMES[k],key='stats_kind_'+room)
    scope=b.selectbox("Default squad scope",['first_team','club','all'],format_func=lambda k:{'first_team':"Leicester first team",'club':"All Leicester squads",'all':"All archived players (including loans)"}[k],key='stats_scope_'+room)
    stats_season=season.strip() or season_for_date(snapshot['game_date'])
    chosen=[names[k] for k in people]
    relevant_lore=[r for r in lore if r['level']=='canon'] if mode=='analysis' else lore
    background=store.lookup_context(chosen,relevant_lore,analytics or [],snapshot,stats_season,kind,scope)
    require_lookup=st.checkbox("Look up evidence before answering",value=True,key='require_lookup_'+room,
        help="Query statistics, performances, injuries or transfers before answering. Disable for pure fiction; the model can still query when useful.")
    st.caption("Detailed data is queried on demand. Analysis and lookup-enabled stories pass through evidence checks. Failures show gaps. Pure fiction can disable this option in the story space. Checks do not certify tactical judgments.")
    with st.expander("Context included in this request"):
        st.caption("Only the save date, archive directory and selected character/story background are preloaded. Not loaded does not mean absent from the database.")
        st.json(json.loads(background))
    history=store.messages(room)
    st.download_button("Back up this chat",json.dumps(history,ensure_ascii=False,indent=2),file_name='dynasty-chat.json',mime='application/json')
    if st.session_state.get('chat_usage_blocked')==selected and selected:
        st.warning("This account reached an app subscription usage limit. Check ChatGPT Settings → Usage. Your message is saved.")
        st.link_button("View ChatGPT Usage",'https://chatgpt.com/#settings/Usage',key='blocked_usage')
        if st.button("Usage checked; try again"):
            st.session_state.pop('chat_usage_blocked',None)
            st.rerun()
        model=None
        model_problem="Subscription usage is limited. Check ChatGPT Usage first."
    if not model:st.warning("Chat unavailable: "+model_problem)
    history_panel=st.container()
    st.markdown("**Send a new message**")
    with st.form('composer_'+room,clear_on_submit=False):
        draft=st.text_input("Message",placeholder="Type a question, then press Enter or Send",key='draft_'+room,disabled=not model)
        submitted=st.form_submit_button("Send",disabled=not model,type='primary')
    prompt=draft.strip() if submitted and draft.strip() else None
    if submitted and not draft.strip():st.warning("Enter a message.")
    active_reply=st.container()
    retry=False
    if history and (history[-1]['role']=='user' or history[-1]['status']=='incomplete'):
        retry=st.button("Retry last message",disabled=not model)
    with history_panel:render_history(history,mode,labels[room],season,chosen)
    if not prompt and not retry:return
    if len(background)>120000:active_reply.error("Archive context exceeds the local size limit. Narrow the squad scope or selected characters and retry; metrics were not silently truncated.");return
    if prompt:
        store.save_message(room,'user',prompt)
        history=store.messages(room)
        active_reply.success("Message saved and processing. The input retains your text to protect against connection loss.")
        active_reply.markdown("**Your question**")
        active_reply.markdown(prompt)
    from src.chat_routing import unsupported_request
    question=next((m['text'] for m in reversed(history) if m['role']=='user'),'')
    unsupported=unsupported_request(question)
    if unsupported:
        message_id=store.save_message(room,'assistant',unsupported['answer'],model='local')
        store.save_workflow(message_id,[{'kind':'request_routing','title':"Request scope check",'elapsed_seconds':0,
            'details':{'question':question,'reason':unsupported['reason'],'model_called':False,'fm_tools_called':False,'evidence_gate':False}}])
        st.rerun()
    background=store.lookup_context(chosen,relevant_lore,analytics or [],snapshot,stats_season,kind,scope,question=question)
    input_messages=[{'role':m['role'],'content':m['text']} for m in history if m['status']=='complete'][-20:]
    if sum(len(m['content']) for m in input_messages)>90000:
        active_reply.error("Recent conversation is too long. Start a new topic; the original is preserved.");return
    from src.evidence_gate import INSTRUCTIONS as GATE_INSTRUCTIONS, validate_answer
    gated=mode=='analysis' or require_lookup
    text=''
    validation_draft=None
    published=False
    message_id=None
    queries=[]
    events=[]
    started=time.monotonic()
    archive_tools=ArchiveTools(snapshot)
    with active_reply:
        with st.expander("Tool calls and SQL · live execution log",expanded=False):
            flow=st.empty()
        def on_event(event):
            events.append({**event,'elapsed_seconds':round(time.monotonic()-started,2)})
            with flow.container():render_trace(events)
        archive_tools.on_event=on_event
        on_event({'kind':'input','title':"Question received; preparing context",'details':{
            'question':next((m['content'] for m in reversed(input_messages) if m['role']=='user'),''),
            'model':model,'snapshot_date':snapshot['game_date'],'discussion_season':stats_season,
            'competition':KIND_NAMES[kind],'scope':scope,'history_messages':len(input_messages),
            'preloaded_players':0,'preloaded_transfers':0,'require_lookup':require_lookup,
            'available_tools':TOOL_LABELS,'note':"Detailed values come from tools. With lookup enabled, name search or directory lookup must be followed by a concrete data query."}})
        placeholder=st.empty()
        query_status=st.empty()
        def on_query(query):
            queries.append(query)
            result=query['result']
            status="Query incomplete" if result.get('error') else f"Found {result['total']} records" if 'total' in result else "Archive scope returned"
            query_status.caption(f"Queried {len(queries)} times · {TOOL_LABELS.get(query['name'],"Archive lookup")} · {status}; continuing analysis…")
        placeholder.info("Request sent; waiting for model output. Detailed analysis may take time. Do not send duplicates.")
        try:
            with st.spinner("Generating a reply…",show_time=True):
                for delta in auth.stream_reply(selected,model,input_messages,store.instructions_for(mode)+'\nResponse language: '+('Simplified Chinese.' if language()=='zh-CN' else 'English.')+AGENT_INSTRUCTIONS+(GATE_INSTRUCTIONS if gated else '')+"\nQuoted archive context:\n"+background,
                                               tools=TOOLS,execute_tool=archive_tools.execute,on_tool=on_query,on_event=on_event,require_lookup=require_lookup,final_text_only=gated):
                    text+=delta
                    if gated:placeholder.info("Generating and checking evidence. Draft text stays hidden until validation…")
                    else:placeholder.markdown(text+' ▌')
            if gated:
                validation_draft=text
                verdict=validate_answer(text,queries,snapshot['game_date'],next((m['content'] for m in reversed(input_messages) if m['role']=='user'),''))
                on_event({'kind':'evidence_check','title':"Pre-answer evidence check",'details':{'passed':verdict['passed'],'errors':verdict['errors'],'warnings':verdict.get('warnings',[]),'partial':verdict.get('partial',False),'verified_facts':verdict.get('verified_facts',[]),'scope':"Checks fields, dates, pagination and selected evidence requirements, not all natural-language reasoning."}})
                text=verdict['text']
            published=True
            placeholder.markdown(text)
            message_id=store.save_message(room,'assistant',text,status='incomplete' if gated and not verdict['passed'] else 'complete',model=model)
            store.save_queries(message_id,queries)
            store.save_workflow(message_id,events,validation_draft=validation_draft)
            st.rerun()
        except auth.ConnectionFailure as exc:
            on_event({'kind':'error','title':"Analysis interrupted",'details':{'message':str(exc)}})
            if gated and not published:text=''
            failure_text=(text+'\n\n' if text else '')+"Response incomplete: "+str(exc)
            message_id=store.save_message(room,'assistant',failure_text,'incomplete',model)
            store.save_queries(message_id,queries)
            store.save_workflow(message_id,events,validation_draft=validation_draft)
            placeholder.empty()
            if text:st.markdown(text)
            if exc.code=='subscription_sharing_usage_limit_exceeded':
                st.session_state.chat_usage_blocked=selected
                st.link_button("View ChatGPT Usage",'https://chatgpt.com/#settings/Usage',key='failed_usage')
            st.error(str(exc))
        finally:
            # Streamlit reruns/stops inherit BaseException; retain evidence even then.
            # Never retry automatically: the previous request may already consume quota.
            if message_id is None:
                events.append({'kind':'interrupted','title':"Generation interrupted before saving the answer",'elapsed_seconds':round(time.monotonic()-started,2),
                    'details':{'note':"Page reruns, session stops or unhandled exceptions may interrupt this round. Completed queries are retained; no automatic model retry."}})
                message_id=store.save_message(room,'assistant',"Generation stopped before a complete answer was saved. Completed queries and execution records are available; no automatic retry occurred.",'incomplete',model)
                store.save_queries(message_id,queries)
                store.save_workflow(message_id,events,validation_draft=validation_draft)


def conversation_turns(history):
    turns=[]
    for message in history:
        if message['role']=='user' or not turns:
            turns.append({'question':message['text'] if message['role']=='user' else "Historical reply",'messages':[]})
        turns[-1]['messages'].append(message)
    return turns


@st.fragment
def render_history(history,mode,title,season,chosen):
    st.caption("Chronological order, collapsed by default. Open a question to read the answer and its tool calls, SQL and results.")
    for index,turn in enumerate(conversation_turns(history),1):
        question=' '.join(turn['question'].split())
        # Escape Markdown so questions remain readable as labels.
        label=question[:140]+('…' if len(question)>140 else '')
        for char in ('\\','*','_','[',']','`'):label=label.replace(char,'\\'+char)
        panel=st.expander(f'{index}. {label}',expanded=False,key='turn_'+turn['messages'][0]['id'],on_change='rerun')
        if not panel.open:continue
        with panel:
            st.markdown("**Your question**")
            st.markdown(turn['question'])
            replies=[m for m in turn['messages'] if m['role']!='user']
            if not replies:st.caption("No complete reply yet. Retry below.")
            for message in replies:
                st.markdown("**Answer**")
                if message['text'].startswith("This response failed evidence validation") and "Query pagination is incomplete" in message['text'] and message.get('queries'):
                    from src.evidence_gate import partial_report
                    st.markdown(partial_report(message['queries']))
                else:st.markdown(message['text'])
                render_usage(message.get('workflow',[]))
                if message.get('workflow') or message.get('queries'):
                    trace_panel=st.expander("Tool calls and SQL",key='trace_'+message['id'],on_change='rerun')
                    with trace_panel:
                        if trace_panel.open:
                            if message.get('workflow'):render_trace(message['workflow'])
                            for n,q in enumerate(message.get('queries',[]),1):
                                with st.expander(f"Query {n} · {TOOL_LABELS.get(q['name'],"Archive lookup")} · Parameters and results"):
                                    st.json(q,expanded=False)
                if message['status']!='complete':st.caption("Reply interrupted · excluded from subsequent complete assistant history")
                if mode=='story' and message['role']=='assistant' and message['status']=='complete':
                    with st.expander("Collect this headcanon"):
                        with st.form('collect_'+message['id']):
                            story_title=st.text_input("Story title",value=title,key='story_'+message['id'])
                            st.caption("Links selected characters and the discussion season. Repeated collection does not create duplicate entries.")
                            if st.form_submit_button("Save as headcanon"):
                                try:store.collect(message['id'],story_title,season,chosen);st.success("Collected. View it in the story archive and linked player profiles.")
                                except ValueError as exc:st.error(str(exc))
