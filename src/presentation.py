"""Presentation over already allowlisted records; no additional save-file access."""
from html import escape
from pathlib import Path
from src.i18n import st

def e(value):
    return escape(str(value if value is not None else '—'))

def initials(name):
    return ''.join(word[0] for word in (name or '?').split()[:2]).upper()

def install_theme():
    st.html('<style>'+Path(__file__).with_name('theme.css').read_text(encoding='utf-8')+'</style>')

def club_header(page, snapshot, season):
    st.html(f'''<div class="club-header"><div class="club-brand"><div class="club-crest">LC<span>DYNASTY</span></div><div><div class="eyebrow">LEICESTER CITY · DYNASTY ARCHIVE</div><div class="club-name">Leicester City<span>Football Club</span></div><div class="muted">{e(snapshot['manager'])} · Dynasty Archive</div></div></div><div class="header-date"><span class="status-dot"></span> Snapshot<strong>{e(snapshot['game_date'])}</strong><span>{e(season)} season</span></div></div>''')
    st.title(page)

def player_card(player, loan=False):
    positions=' / '.join(player['natural_positions']) or "Position not recorded"
    st.html(f'''<div class="player-card"><div class="player-card-top"><span class="position-badge">{e(positions)}</span><span class="muted">{"On loan" if loan else "Home club"}</span></div><div class="player-card-body"><div class="kit">{e(initials(player['name']))}</div><div><div class="player-name">{e(player['name'])}</div><div class="muted">{e(player['age'])} years <span class="sep">/</span> {e(player['height_cm'])} cm</div></div></div><div class="player-card-bottom"><span>{e(player['club_name'])}</span><span>Contract {e(player['contract_end'])}</span></div></div>''')

def profile_banner(player):
    st.html(f'''<div class="profile-banner"><div class="kit large">{e(initials(player['name']))}</div><div><div class="eyebrow">PLAYER PROFILE</div><div class="profile-name">{e(player['name'])}</div><div class="muted">{e(' / '.join(player['natural_positions']))} · {e(player['age'])} years · {e(player['height_cm'])} cm</div></div></div>''')

def transfer_board(rows,direction):
    label="In" if direction=='in' else "Out"
    subset=sorted((r for r in rows if r['direction']==direction),key=lambda r:r['date'],reverse=True)
    if not subset:return
    color='incoming' if direction=='in' else 'outgoing'
    body=''
    for r in subset:
        body+=f'''<tr><td class="transfer-date">{e(r['date'])}<small>{e(r['season'])}</small></td><td><div class="transfer-person"><span class="avatar">{e(initials(r['player_name']))}</span><strong>{e(r['player_name'])}</strong></div></td><td class="transfer-club">{e(r['other_club'])}</td><td><span class="fee {'loan' if r['kind']=='loan' else ''}">{e(r['fee_display'])}</span></td></tr>'''
    st.html(f'''<section class="transfer-panel {color}"><div class="panel-heading"><span class="transfer-arrow">{'↙' if direction=='in' else '↗'}</span><h3>{label}</h3><span class="count-pill">{len(subset)}</span><span class="panel-note">Archived by actual transfer date</span></div><div class="table-scroll"><table class="fm-table"><thead><tr><th>Date / Season</th><th>Player</th><th>{"From" if direction=='in' else "To"}</th><th>Fee</th></tr></thead><tbody>{body}</tbody></table></div></section>''')

ATTRIBUTE_LABELS=dict(zip('crossing dribbling finishing heading long_shots marking off_the_ball passing penalty_taking tackling vision handling aerial_reach command_of_area communication kicking throwing anticipation decisions one_on_ones positioning reflexes first_touch technique flair corners teamwork work_rate long_throws eccentricity rushing_out punching acceleration free_kick_taking strength stamina pace jumping_reach leadership balance bravery aggression agility natural_fitness determination composure concentration'.split(), "Crossing Dribbling Finishing Heading Long_shots Marking Off_the_ball Passing Penalties Tackling Vision Handling Aerial_reach Command_of_area Communication Kicking Throwing Anticipation Decisions One_on_ones Positioning Reflexes First_touch Technique Flair Corners Teamwork Work_rate Long_throws Eccentricity Rushing_out Punching Acceleration Free_kicks Strength Stamina Pace Jumping_reach Leadership Balance Bravery Aggression Agility Natural_fitness Determination Composure Concentration".split()))

ATTRIBUTE_LABELS = {key: value.replace('_', ' ') for key, value in ATTRIBUTE_LABELS.items()}

def attribute_panel(attributes):
    physical=set('acceleration strength stamina pace jumping_reach balance agility natural_fitness'.split())
    mental=set('off_the_ball vision anticipation decisions positioning flair teamwork work_rate leadership bravery aggression determination composure concentration'.split())
    groups=[("Technical and goalkeeping",[(k,v) for k,v in attributes.items() if k not in physical|mental]),("Mental",[(k,v) for k,v in attributes.items() if k in mental]),("Physical",[(k,v) for k,v in attributes.items() if k in physical])]
    for col,(label,items) in zip(st.columns(3),groups):
        with col:
            lines=''.join(f'<div class="attribute"><span>{e(ATTRIBUTE_LABELS.get(k,k.replace("_"," ").title()))}</span><b class="{"elite" if v is not None and v>=16 else "good" if v is not None and v>=11 else "normal"}">{e(v)}</b></div>' for k,v in items)
            st.html(f'<section class="attribute-panel"><h4>{label}</h4>{lines}</section>')
