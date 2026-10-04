from __future__ import annotations

import json
from src.i18n import st
from src.archive import snapshots, squad, history
from src.lore import load_lore, LEVELS
from src.conversations import load_conversation, matching_passages, people_in, normalized
from datetime import datetime, timezone
from src.analytics_ui import load_data, render as render_analytics, person_panel
from src.presentation import install_theme, club_header, player_card, profile_banner, attribute_panel

st.set_page_config(page_title="Leicester Dynasty Archive", page_icon="🦊", layout="wide")
from src.i18n import CATALOG
if 'ui_language' not in st.session_state:
    st.session_state['ui_language']='zh-CN' if st.query_params.get('lang')=='zh-CN' else 'en'
lang=st.sidebar.selectbox('Language', ['en','zh-CN'], format_func=lambda x:'English' if x=='en' else '中文', key='ui_language')
st.query_params['lang']=lang
install_theme()

def story_cards(entries):
    if not entries:
        st.caption("No records yet. This space is reserved for sourced facts and your own stories.")
    for entry in entries:
        with st.container(border=True):
            st.caption(f"{entry['level'].upper()} · {LEVELS[entry['level']]} · {entry['season'] or "Unspecified period"}")
            st.markdown(f"**{entry['title']}**")
            st.write(entry["text"])
            st.caption("Source: " + entry["source"])


def source_passages(records, prefix):
    if len(records)>40:
        page=st.number_input('Original passage page',min_value=1,max_value=(len(records)+39)//40,value=1,key='passage_page_'+prefix)
        records=records[(page-1)*40:page*40]
    for record in records:
        role = "You" if record['role'] == 'user' else 'ChatGPT'
        with st.expander(f"{role} · {record['title']}"):
            st.caption("Original conversation · not automatically treated as game facts")
            st.markdown(record['text'])
            st.caption(f"Message {record['message_id']} · Original characters {record['start']}–{record['end']}")


all_snapshots = snapshots()
st.sidebar.markdown("### LEICESTER CITY")
st.sidebar.caption("D Y N A S T Y  A R C H I V E")
st.sidebar.divider()
if st.sidebar.button("Update latest save",help="Run after the game finishes saving. Backs up, validates and imports locally without AI."):
    import subprocess,sys
    from src.safe_export import ROOT
    with st.spinner("Backing up, validating and importing the latest save. Please wait…"):
        result=subprocess.run([sys.executable,'-X','utf8','-m','src.sync_save'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if result.returncode:
        st.error("Update incomplete.")
        st.code(result.stdout)
        st.stop()
    st.session_state['sync_notice']=result.stdout.splitlines()[-1]
    st.cache_data.clear()
    st.rerun()
if st.session_state.get('sync_notice'):st.sidebar.success(st.session_state.pop('sync_notice'))
if not all_snapshots:
    st.title("Leicester Dynasty Archive")
    st.info("No save has been imported. Run the project's import script first.")
    st.stop()
snapshot = st.sidebar.selectbox("Snapshot", all_snapshots,
                               format_func=lambda s: f"{s['game_date']} · Snapshot {s['id']}")
archive_pages = ["Current squad", "Dressing room chat", "Season and competition statistics", "Premier League snapshots", "Transfer archive", "Story archive", "Conversation originals", "Database workbench", "Data checks"]
requested_page = st.query_params.get("page", "Current squad")
requested_page = next((en for en,zh in CATALOG.items() if zh==requested_page and en in archive_pages),requested_page)
page = st.sidebar.radio("Browse", archive_pages, index=archive_pages.index(requested_page) if requested_page in archive_pages else 0)
st.sidebar.divider()
st.sidebar.caption("Facts, inferences and headcanon are labeled separately.")
st.sidebar.caption("Only manager-visible information is displayed.")
players = squad(snapshot["id"])
analytics = load_data(snapshot['game_date'])
current_extra = next((d for d in analytics if d['snapshot']['sha256']==snapshot['sha256']),None)
loan_players = [p['player'] for p in current_extra['players'] if p['membership']=='loan_out'] if current_extra else []
loan_keys = {p['identity_key'] for p in loan_players}
registered_count = len(players)
players = sorted(players+loan_players,key=lambda p:(p['name'] or '').casefold())
conversation = load_conversation()
try:
    entries = load_lore()
except (ValueError, OSError, KeyError, TypeError):
    st.error("The manual story file is invalid. Stories are hidden; check data/manual/lore.json.")
    entries = []

year, month, _ = map(int, snapshot["game_date"].split("-"))
season_start = year if month >= 7 else year - 1
club_header(page,snapshot,f'{season_start}/{str(season_start + 1)[-2:]}')

if page == "Current squad":
    a, b, c, d = st.columns(4)
    a.metric("First-team players", sum(p["team_slot"] == 0 and p['identity_key'] not in loan_keys for p in players))
    b.metric("Registered club players", registered_count)
    c.metric("Archived snapshots", len(all_snapshots))
    d.metric("Players on loan",len(loan_players))
    st.caption("First team · youth squads · players on loan")
    a, b, c = st.columns([2, 1, 1])
    search = a.text_input("Search name", placeholder="For example Monga, Page, Shaw")
    slots = ["All", "On loan"] + [f"Slot {slot}" for slot in sorted({p["team_slot"] for p in players if p["team_slot"] is not None})]
    scope = b.selectbox("Squad scope", slots, index=slots.index("Slot 0") if "Slot 0" in slots else 0,format_func=lambda x:"First team" if x=="Slot 0" else x.replace("Slot ","Squad "))
    positions = ["All"] + sorted({pos for p in players for pos in p["natural_positions"]})
    position = c.selectbox("Natural position", positions)
    visible = [p for p in players if search.casefold() in (p["name"] or "").casefold()
               and (scope == "All" or (scope == "On loan" and p['identity_key'] in loan_keys) or (scope == f"Slot {p['team_slot']}" and p['identity_key'] not in loan_keys))
               and (position == "All" or position in p["natural_positions"])]
    st.subheader("Current squad")
    st.caption(f"{len(visible)} players · select a card to open a profile")
    table = [{"Name": p["name"], "Age": p["age"], "Natural position": " / ".join(p["natural_positions"]),
              "Club":p['club_name'],"Membership":"On loan" if p['identity_key'] in loan_keys else "Registered here",
              "Contract expiry": p["contract_end"], "Height cm": p["height_cm"]} for p in visible]
    if not visible:
        st.info("No players match these filters.")
        st.stop()
    player_keys=[p['identity_key'] for p in visible]
    if st.session_state.get('profile_choice') not in player_keys:
        st.session_state['profile_choice']=player_keys[0]
    pages=max(1,(len(visible)+5)//6)
    card_page=st.selectbox("Squad page",range(pages),format_func=lambda x:f'Page {x+1} / {pages} ',key=f'roster_page_{snapshot["id"]}_{scope}_{position}_{search}')
    card_columns=st.columns(3)
    for i,p in enumerate(visible[card_page*6:card_page*6+6]):
        with card_columns[i%3]:
            with st.container(border=True):
                player_card(p,p['identity_key'] in loan_keys)
                if st.button("View profile →",key='open_'+p['identity_key'],width='stretch',type='primary' if st.session_state['profile_choice']==p['identity_key'] else 'secondary'):
                    st.session_state['profile_choice']=p['identity_key']
    with st.expander("Full squad / table view"):
        st.dataframe(table,hide_index=True,width='stretch')
    chosen=st.selectbox("Player profile",player_keys,format_func=lambda key:next(p['name'] or key for p in visible if p['identity_key']==key),key='profile_choice')
    selected=next(p for p in visible if p['identity_key']==chosen)
    st.divider()
    profile_banner(selected)
    details, attributes, sporting, stories, timeline = st.tabs(["Player details", "Visible attributes", "Matches and history", "Player stories", "Snapshot history"])
    with sporting:
        person_panel(analytics,selected['identity_key'])
    with details:
        a, b = st.columns(2)
        a.write(f"Date of birth: {selected['birth_date'] or "Not available"}")
        a.write(f"Joined club: {selected['club_join_date'] or "Not available"}")
        a.write(f"Contract expiry: {selected['contract_end'] or "Not available"}")
        b.write(f"Contract role: {selected['squad_status'] or "Not available"}")
        b.write(f"Nationality ID: {selected['nation_id'] if selected['nation_id'] is not None else "Not available"}")
        b.caption("Country names are not verified; IDs are retained for now.")
        if selected["on_loan"]:
            st.write(f"Loaned from: {selected['loan_parent_club_name'] or "Not available"}")
        st.caption("Source: current save parsed by fmsave; individual fields have not all been checked against the game. Missing is not zero.")
        with st.expander("Manual story linking key"):
            st.code(selected["identity_key"], language=None)
    with attributes:
        st.caption("Visible 1–20 attributes; excludes hidden attributes and exact positional proficiency.")
        attribute_panel(selected['attributes'])
    with stories:
        relevant = [e for e in entries if selected["identity_key"] in e["player_keys"]]
        for level, label in LEVELS.items():
            st.markdown(f"#### {label} · {level}")
            story_cards([e for e in relevant if e["level"] == level])
        st.markdown("#### Mentions in original conversations")
        st.caption("Includes historical claims, examples and ideas. Original context is preserved, not automatically promoted to canon.")
        related = matching_passages(conversation, person=selected['name'])
        source_passages(related, selected['identity_key'])
    with timeline:
        st.dataframe(history(selected["identity_key"], through_date=snapshot["game_date"]), hide_index=True)
        st.caption("Only imported snapshots up to the selected date are shown. Missing historical seasons are not fabricated.")
elif page == "Dressing room chat":
    from src.chat_ui import render as render_chat
    render_chat(players,entries,snapshot,analytics)
elif page == "Transfer archive":
    from src.transfers import render as render_transfers
    render_transfers()
elif page == "Season and competition statistics":
    render_analytics(analytics,snapshot['club_uid'])
elif page == "Story archive":
    st.subheader("Dressing room and club memories")
    st.info("Imported conversation memory is searchable in Conversation originals and by the chat memory tool. Curated stories remain separate from unreviewed historical discussion.")
    st.caption("Earlier story settings retain their sources. Save imports do not overwrite manual stories. Excerpts and edited entries may describe the same event.")
    levels = st.multiselect("Evidence level", list(LEVELS), default=list(LEVELS), format_func=lambda x: f"{x} · {LEVELS[x]}")
    a,b = st.columns(2)
    story_query = a.text_input("Search stories",placeholder="For example dressing room, Oscar, Again")
    story_person = b.selectbox("Story characters (including former players)",["All"] + sorted({name for e in entries for name in e['player_names']}))
    filtered_entries=[e for e in entries if e['level'] in levels
                      and (story_person == "All" or story_person in e['player_names'])
                      and normalized(story_query) in normalized(e['title']+' '+e['text'])]
    st.caption(f'Showing {len(filtered_entries)} / archived total {len(entries)} records')
    story_cards(filtered_entries)
    st.info("Edit data/manual/lore.json and refresh. Every entry must have a level and source.")
elif page == "Conversation originals":
    st.subheader("FM26 scouting budget discussion · original archive")
    st.info("Complete supplied text export imported, including alternate branches. Image references are retained, but image files are not included." if conversation['coverage']['full_history_available'] else "Partial import: earlier records are unavailable.")
    a,b,c=st.columns(3)
    a.metric("Saved messages",len(conversation['messages']))
    b.metric("Saved original characters",sum(len(m['text']) for m in conversation['messages']))
    c.metric("Archived original passages",sum(e['id'].startswith('chat-') for e in entries))
    st.caption("Preserves user and assistant messages, including discussion, stories, historical claims and project ideas. Original labels are not verified canon.")
    st.download_button("Download retrieved conversation backup",json.dumps(conversation,ensure_ascii=False,indent=2),
                       file_name='FM26-scout-budget-partial.json',mime='application/json')
    read,find=st.tabs(["Read by message","Search by player or keyword"])
    with read:
        messages=conversation['messages']
        message=st.selectbox("Select message",messages,format_func=lambda m:
            f"{messages.index(m)+1:02d} · {"You" if m['role']=='user' else 'ChatGPT'} · {m['text'][:65].split(chr(10))[0]}")
        st.caption((datetime.fromtimestamp(message['timestamp'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if message['timestamp'] is not None else 'Timestamp unavailable')+' · '+message['id']+' · '+message.get('branch','CURRENT'))
        st.markdown(message['text'])
    with find:
        a,b,c=st.columns([2,1,1])
        query=a.text_input("Search original text",placeholder="For example Suslov, Germany, 90+5")
        person=b.selectbox("People in originals (including former players)",["All"]+sorted({name for m in conversation['messages'] for name in people_in(m['text'])}))
        role=c.selectbox("Speaker",["All",'user','assistant'],format_func=lambda r: {"All":"All",'user':"You",'assistant':'ChatGPT'}[r])
        records=matching_passages(conversation,query,role,person)
        st.caption(f'Found {len(records)} original passages. Expand a title to read the full text and source.')
        source_passages(records,'archive')
elif page == "Premier League snapshots":
    from src.league_ui import render as render_league
    render_league()
elif page == "Database workbench":
    from src.sql_console import render as render_sql
    render_sql()
else:
    st.subheader("What this snapshot can establish")
    checks = json.loads(snapshot["validation_json"])
    failed = [row["reader"] for row in checks if row["status"] != "ok"]
    if failed:
        st.warning("Full validation has unresolved checks: " + ", ".join(failed) + ". This version does not use those records.")
    st.dataframe(checks, hide_index=True)
    if current_extra:
        st.markdown("**Extended statistics checks**")
        st.dataframe(current_extra['checks'],hide_index=True)
        if any(r['status']!='ok' for r in current_extra['checks']):
            st.warning("injury_types name validation failed. Independently validated injury dates are retained; names remain empty.")
    st.write(f"FM build: {snapshot['build']} · fmsave: {snapshot['fmsave_version']}")
    st.write(f"Missing names: {sum(not p['name'] for p in players)} / Missing contract expiry: {sum(not p['contract_end'] for p in players)}")
    st.caption("The allowlist is checked at export, import and squad read time. CA, PA, hidden personality and reputation values are not stored.")
    st.caption("Backup checksum (SHA-256): " + snapshot["sha256"])
