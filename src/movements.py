"""Squad movements of the managed club, inferred from consecutive archived snapshots.

A movement is only known to have happened between two snapshots (its window). An exact date is
added when the save records one inside that window. Fees never come from the save: they are
attached only from screenshot-backed transfer events with the same player, direction and kind.
"""
import json
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date, timedelta

LONG_GAP_DAYS = 90
INCOMING = {'joined', 'youth_intake', 'loan_in', 'signed_permanently', 'loan_returned'}
FIELDS = ('player_name', 'movement', 'direction', 'club', 'date', 'date_basis', 'window_start', 'window_end', 'gap_days',
          'fee_display', 'fee_eur_displayed', 'screenshot_date', 'screenshot_other_club', 'source', 'note', 'identity_key')
# Which screenshot kind and direction can confirm which inferred movement.
SCREENSHOT_MATCH = {('in', 'transfer'): {'joined', 'signed_permanently'}, ('in', 'loan'): {'loan_in'},
                    ('out', 'transfer'): {'left', 'left_while_on_loan'}, ('out', 'loan'): {'loaned_out'}}
SCREENSHOT_ONLY = {('in', 'transfer'): 'joined', ('in', 'loan'): 'loan_in', ('out', 'transfer'): 'left', ('out', 'loan'): 'loaned_out'}


def _name(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', (value or '').casefold()) if not unicodedata.combining(c))


def _states(payload):
    states = {}
    for record in payload.get('players', []):
        player = record.get('player') or {}
        key = player.get('identity_key')
        if not key:
            continue
        state = 'loan_out' if record.get('membership') == 'loan_out' else 'loan_in' if player.get('on_loan') else 'own'
        states[key] = dict(state=state, name=player.get('name'), club=player.get('club_name'), join=player.get('club_join_date'),
                           contract_start=record.get('contract_start'), loan_start=record.get('loan_start'), loan_end=record.get('loan_end'),
                           parent=player.get('loan_parent_club_name'), age=player.get('age'), slot=player.get('team_slot'),
                           contract_end=player.get('contract_end'))
    return states


def _chains(payload):
    chains = {}
    for contract in payload.get('contracts', []):
        chains.setdefault(contract.get('identity_key'), []).append(contract)
    return chains


def _diff(previous, current):
    start, before, chains, own_club = previous
    end, after = current[0], current[1]
    gap = (date.fromisoformat(end) - date.fromisoformat(start)).days
    rows = []
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        x, y = (a or {}).get('state'), (b or {}).get('state')
        if x == y and not (x == 'loan_out' and a['club'] != b['club']):
            continue
        row = dict.fromkeys(FIELDS)
        row.update(identity_key=key, player_name=(b or a)['name'], window_start=start, window_end=end, gap_days=gap, source='snapshots')

        def dated(day, basis):
            if day and start < day <= end and not row['date']:
                row.update(date=day, date_basis=basis)

        if x is None:
            if y == 'loan_in':
                row.update(movement='loan_in', club=b['parent'])
            elif not b['join'] and (b['slot'] or 0) > 0 and (b['age'] or 99) <= 17:
                row.update(movement='youth_intake')
                dated(b['contract_start'], 'contract_start')
            else:
                row.update(movement='joined')
                dated(b['join'], 'club_join_date')
                dated(b['contract_start'], 'contract_start')
                if y == 'loan_out':
                    row['note'] = f"Joined and was loaned out to {b['club']} before the next snapshot."
        elif y is None:
            if x == 'loan_in':
                row.update(movement='loan_ended', club=a['parent'])
            else:
                agreed = sorted((c for c in chains.get(key, []) if c.get('club_uid') != own_club and c.get('start') and c['start'] > start),
                                key=lambda c: c['start'])
                row.update(movement='left_while_on_loan' if x == 'loan_out' else 'left')
                if agreed:
                    row.update(club=agreed[0].get('club_name'), date=agreed[0]['start'], date_basis='agreed_contract_start',
                               note='Destination is the next agreed contract seen at the earlier snapshot; the save does not say whether it was a loan or a transfer.')
                elif x == 'loan_out':
                    row.update(club=a['club'], note='Left while on loan at this club; the save does not confirm the destination.')
                else:
                    row['note'] = 'Destination not in the save.' + (f" Contract was due to end {a['contract_end']}." if a['contract_end'] else ' No contract was recorded.')
        elif y == 'loan_out':
            row.update(movement='loaned_out', club=b['club'])
            dated(b['loan_start'], 'loan_start')
        elif x == 'loan_out':
            row.update(movement='loan_returned', club=a['club'])
            dated(a['loan_end'], 'loan_end')
        elif x == 'loan_in' and y == 'own':
            row.update(movement='signed_permanently', club=a['parent'])
            dated(b['join'], 'club_join_date')
        else:
            continue
        row['direction'] = 'in' if row['movement'] in INCOMING else 'out'
        if gap > LONG_GAP_DAYS:
            row['note'] = ((row['note'] + ' ') if row['note'] else '') + f'Snapshots are {gap} days apart, so other moves in between may be missing.'
        rows.append(row)
    return rows


def infer(snapshots):
    """Movements between consecutive snapshots; snapshots are analytics payloads ordered by game date."""
    rows, previous = [], None
    for payload in snapshots:
        current = (payload['snapshot']['date'], _states(payload), _chains(payload), payload['snapshot'].get('club_uid'))
        if previous and previous[0] != current[0]:
            rows.extend(_diff(previous, current))
        previous = current
    return rows


def attach_screenshots(rows, events, tolerance_days=7):
    """Attach screenshot fees to matching inferred movements; unmatched screenshot events are kept as their own rows."""
    used = set()
    margin = timedelta(days=tolerance_days)
    # Dated movements claim their screenshot first, so an undated one in a long window cannot take it.
    for row in sorted(rows, key=lambda r: r['date'] is None):
        low, high = date.fromisoformat(row['window_start']) - margin, date.fromisoformat(row['window_end']) + margin
        candidates = [(i, event) for i, event in enumerate(events)
                      if i not in used and row['movement'] in SCREENSHOT_MATCH.get((event['direction'], event['kind']), ())
                      and _name(event['player_name']) == _name(row['player_name']) and low <= date.fromisoformat(event['date']) <= high]
        if row['date']:
            # With an exact date, only a screenshot within the tolerance can describe the same move.
            day = date.fromisoformat(row['date'])
            distance = lambda c: abs((date.fromisoformat(c[1]['date']) - day).days)
            candidates = sorted((c for c in candidates if distance(c) <= tolerance_days), key=distance)
        else:
            # Without a date, the latest move in the window is the one that changed the next snapshot.
            candidates.sort(key=lambda c: c[1]['date'], reverse=True)
        if candidates:
            i, event = candidates[0]
            used.add(i)
            row.update(fee_display=event.get('fee_display'), fee_eur_displayed=event.get('fee_eur_displayed'), screenshot_date=event['date'],
                       screenshot_other_club=event.get('other_club'), source='snapshots+screenshot')
    for i, event in enumerate(events):
        if i in used:
            continue
        row = dict.fromkeys(FIELDS)
        row.update(player_name=event['player_name'], movement=SCREENSHOT_ONLY[(event['direction'], event['kind'])], direction=event['direction'],
                   club=event.get('other_club'), date=event['date'], date_basis='screenshot', fee_display=event.get('fee_display'),
                   fee_eur_displayed=event.get('fee_eur_displayed'), screenshot_date=event['date'], screenshot_other_club=event.get('other_club'),
                   source='screenshot', note=event.get('note') or None)
        rows.append(row)
    return sorted(rows, key=lambda r: (r['date'] or r['window_end'] or '', r['player_name'] or ''))


def in_range(row, start, end):
    """Certainly in range: its known date is, or, without a date, its whole window lies inside the range."""
    if row['date']:
        return start <= row['date'] <= end
    return row['window_start'] >= start and row['window_end'] <= end


def partly_in_range(row, start, end):
    """Undated movement whose window only partly overlaps the range: it may or may not have happened in it."""
    return not row['date'] and not in_range(row, start, end) and row['window_start'] < end and row['window_end'] >= start


def read_movements(db, through=None):
    """All movements up to an optional game date, for the archive page."""
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as con:
            payloads = [json.loads(r[0]) for r in con.execute(
                'SELECT payload_json FROM analytics_snapshots WHERE ? IS NULL OR game_date<=? ORDER BY game_date,sha256', (through, through))]
            events = [json.loads(r[0]) for r in con.execute(
                'SELECT payload_json FROM transfer_events WHERE ? IS NULL OR date<=? ORDER BY date,id', (through, through))]
    except sqlite3.OperationalError:
        return []  # An archive without imports has no movement tables yet.
    return attach_screenshots(infer(payloads), events)
