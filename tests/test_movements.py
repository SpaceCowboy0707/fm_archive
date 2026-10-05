import unittest
from src.movements import infer, attach_screenshots, in_range, partly_in_range


def player(key, membership='registered', **fields):
    base = dict(identity_key=key, name=key.title(), club_name='Own FC', club_join_date=None, on_loan=False,
                loan_parent_club_name=None, age=25, team_slot=0, contract_end='2040-06-30')
    loan = {k: fields.pop(k) for k in ('loan_start', 'loan_end', 'contract_start') if k in fields}
    return dict(membership=membership, player={**base, **fields}, **loan)


def snapshot(day, players, contracts=()):
    return dict(snapshot=dict(date=day, club_uid=1), players=players, contracts=list(contracts))


class MovementTests(unittest.TestCase):
    def test_each_kind_of_squad_change(self):
        first = snapshot('2036-01-01', [
            player('leaver'), player('loanee', on_loan=True, loan_parent_club_name='Parent FC'), player('lent', 'loan_out', club_name='Away FC', loan_end='2036-01-20'),
            player('stays'), player('reloan', 'loan_out', club_name='First Loan FC'), player('free')],
            contracts=[dict(identity_key='leaver', club_uid=9, club_name='Buyer FC', start='2036-01-15')])
        second = snapshot('2036-02-01', [
            player('newcomer', club_join_date='2036-01-10'), player('kid', age=16, team_slot=2, contract_start='2036-01-12'),
            player('lent', club_name='Own FC'), player('stays', 'loan_out', club_name='Loan FC', loan_start='2036-01-05'),
            player('reloan', 'loan_out', club_name='Second Loan FC')])
        rows = {r['identity_key']: r for r in infer([first, second])}
        expect = {'leaver': ('left', 'Buyer FC', '2036-01-15', 'agreed_contract_start'), 'loanee': ('loan_ended', 'Parent FC', None, None),
                  'lent': ('loan_returned', 'Away FC', '2036-01-20', 'loan_end'), 'stays': ('loaned_out', 'Loan FC', '2036-01-05', 'loan_start'),
                  'reloan': ('loaned_out', 'Second Loan FC', None, None), 'newcomer': ('joined', None, '2036-01-10', 'club_join_date'),
                  'kid': ('youth_intake', None, '2036-01-12', 'contract_start'), 'free': ('left', None, None, None)}
        for key, (movement, club, day, basis) in expect.items():
            r = rows[key]
            self.assertEqual((r['movement'], r['club'], r['date'], r['date_basis']), (movement, club, day, basis), key)
            self.assertEqual((r['window_start'], r['window_end'], r['gap_days']), ('2036-01-01', '2036-02-01', 31))
        self.assertEqual(rows['newcomer']['direction'], 'in');self.assertEqual(rows['leaver']['direction'], 'out')
        self.assertIn('Destination not in the save', rows['free']['note'])

    def test_dates_outside_the_window_are_not_claimed_and_long_gaps_are_flagged(self):
        rows = infer([snapshot('2030-01-01', []), snapshot('2031-01-01', [player('old', club_join_date='2029-05-01')])])
        self.assertIsNone(rows[0]['date']);self.assertIn('365 days apart', rows[0]['note'])
        self.assertEqual(infer([snapshot('2030-01-01', [player('a')])]), [])

    def test_left_while_on_loan_keeps_the_loan_club_as_unconfirmed(self):
        rows = infer([snapshot('2036-01-01', [player('away', 'loan_out', club_name='Loan FC')]), snapshot('2036-02-01', [])])
        self.assertEqual((rows[0]['movement'], rows[0]['club']), ('left_while_on_loan', 'Loan FC'))
        self.assertIn('does not confirm', rows[0]['note'])

    def test_screenshots_attach_to_the_nearest_matching_move_and_the_rest_are_kept(self):
        rows = infer([snapshot('2033-01-01', [player('murray')]), snapshot('2035-12-01', [player('murray', 'loan_out', club_name='Lille', loan_start='2035-09-03')])])
        events = [dict(player_name='Murray', direction='out', kind='loan', date='2034-08-19', other_club='Barcelona', fee_display='Loan', fee_eur_displayed=None),
                  dict(player_name='Murray', direction='out', kind='loan', date='2035-09-03', other_club='LOSC', fee_display='Loan', fee_eur_displayed=None),
                  dict(player_name='Murray', direction='in', kind='transfer', date='2035-09-03', other_club='X', fee_display='€1M', fee_eur_displayed=1000000)]
        merged = attach_screenshots(rows, events)
        inferred = next(r for r in merged if r['source'] == 'snapshots+screenshot')
        self.assertEqual((inferred['screenshot_date'], inferred['screenshot_other_club']), ('2035-09-03', 'LOSC'))
        self.assertEqual(sorted(r['date'] for r in merged if r['source'] == 'screenshot'), ['2034-08-19', '2035-09-03'])
        self.assertEqual([r['date'] or r['window_end'] for r in merged], sorted(r['date'] or r['window_end'] for r in merged))

    def test_range_uses_exact_date_or_overlapping_window(self):
        dated = dict(date='2036-01-10', window_start='2036-01-01', window_end='2036-02-01')
        undated = dict(date=None, window_start='2036-01-01', window_end='2036-02-01')
        self.assertTrue(in_range(dated, '2036-01-05', '2036-01-15'));self.assertFalse(in_range(dated, '2036-01-11', '2036-03-01'))
        self.assertTrue(in_range(undated, '2036-01-01', '2036-03-01'))
        self.assertFalse(in_range(undated, '2036-01-20', '2036-03-01'));self.assertTrue(partly_in_range(undated, '2036-01-20', '2036-03-01'))
        self.assertFalse(partly_in_range(undated, '2036-02-02', '2036-03-01'));self.assertFalse(partly_in_range(dated, '2036-01-11', '2036-03-01'))


if __name__ == '__main__':
    unittest.main()
