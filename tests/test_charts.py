import json
import unittest
from src.charts import resolve
from src.evidence_gate import validate_answer


def query(rows, name='league_team_data', **extra):
    return dict(name=name, arguments={'season': '2035/36'}, result=dict(snapshot_date='2036-03-04', total=len(rows), offset=0, next_offset=None, rows=rows, **extra))


PLAYERS = [dict(player_name='A', goals=10, expected_goals=7.5, assists=2), dict(player_name='B', goals=3, expected_goals=4.25, assists=8),
           dict(player_name='C', goals=None, expected_goals=1.0, assists=1), dict(player_name='D', goals=6, expected_goals=6.0, assists=0)]


class ChartTests(unittest.TestCase):
    def test_values_come_from_the_records(self):
        c = resolve(dict(type='scatter', title='xG vs goals', query=0, records=['rows'], label='player_name', x='expected_goals', y=['goals'], diagonal=True), [query(PLAYERS)])
        self.assertEqual([(p['label'], p['x'], p['y']) for p in c['points']], [('A', 7.5, [10]), ('B', 4.25, [3]), ('D', 6.0, [6])])
        self.assertEqual((c['skipped'], c['diagonal'], c['x_label'], c['y_labels']), (1, True, 'expected_goals', ['goals']))
        bars = resolve(dict(type='hbar', title='Output', query=0, records=['rows'], label='player_name', y=['goals', 'assists'], limit=2), [query(PLAYERS)])
        self.assertEqual([p['label'] for p in bars['points']], ['A', 'D'])

    def test_columnar_metrics_pages_and_line_order(self):
        rows = [dict(name='A', totals=[5, 1, 3.2]), dict(name='B', totals=[2, 4, 2.1])]
        c = resolve(dict(type='bar', title='t', query=0, records=['rows'], label='name', y=[['totals', 0]]), [query(rows, 'squad_attack_comparison', metric_columns=['goals', 'assists', 'expected_goals'])])
        self.assertEqual(c['y_labels'], ['goals (totals)'])
        pages = resolve(dict(type='bar', title='t', query=[0, 1], records=['rows'], label='player_name', y='goals'), [query(PLAYERS[:2]), query(PLAYERS[3:])])
        self.assertEqual(len(pages['points']), 3)
        line = resolve(dict(type='line', title='t', query=0, records=['rows'], x='date', y=['goals']), [query([dict(date='2036-02-01', goals=4), dict(date='2036-01-01', goals=2)])])
        self.assertEqual([p['x'] for p in line['points']], ['2036-01-01', '2036-02-01'])

    def test_pie_folds_small_slices_into_other(self):
        rows = [dict(player_name=str(i), goals=10 - i) for i in range(10)]
        c = resolve(dict(type='pie', title='Goal share', query=0, records=['rows'], label='player_name', y=['goals'], limit=4), [query(rows)])
        self.assertEqual([p['label'] for p in c['points']], ['0', '1', '2', 'Other'])
        self.assertEqual(c['points'][-1]['y'], [sum(range(1, 8))]);self.assertEqual(c['folded'], 7)

    def test_invalid_specs_explain_why(self):
        base = dict(type='bar', title='t', query=0, records=['rows'], label='player_name', y=['goals'])
        cases = [({**base, 'type': 'radar'}, 'type must be'), ({**base, 'query': 3}, 'query_index'), ({**base, 'y': ['player_name']}, 'not a number'),
                 ({**base, 'label': None}, 'needs label'), ({**base, 'type': 'scatter'}, 'needs x'), ({**base, 'values': [1, 2]}, 'needs type'),
                 ({**base, 'query': [0, 1]}, 'same tool'), ({**base, 'records': ['missing']}, 'non-empty list')]
        queries = [query(PLAYERS), query(PLAYERS, 'season_statistics')]
        for spec, reason in cases:
            with self.assertRaisesRegex(ValueError, reason):resolve(spec, queries)
        with self.assertRaisesRegex(ValueError, 'conversation memory'):resolve(base, [query(PLAYERS, 'story_memory')])

    def test_answer_places_valid_charts_and_drops_invalid_ones(self):
        good = dict(type='bar', title='Goals', query=0, records=['rows'], label='player_name', y=['goals'])
        doc = dict(season='2035/36', comparison_player_ids=[], facts=[dict(query=0, path=['rows', 0, 'goals'], value=10)],
                   analysis='Intro\n[[chart:1]]\nOutro', charts=[good, {**good, 'y': ['player_name']}])
        r = validate_answer(json.dumps(doc), [query(PLAYERS)], '2036-03-04')
        self.assertTrue(r['passed']);self.assertEqual(r['charts'], ['Goals'])
        block = r['text'].split('```chart\n')[1].split('\n```')[0]
        self.assertEqual([p['y'] for p in json.loads(block)['points']], [[10], [6], [3]])
        self.assertLess(r['text'].index('Intro'), r['text'].index('```chart'));self.assertLess(r['text'].index('```chart'), r['text'].index('Outro'))
        self.assertIn('Chart 2 was omitted', r['text'])
        doc['charts'] = 'not a list'
        self.assertTrue(validate_answer(json.dumps(doc), [query(PLAYERS)], '2036-03-04')['passed'])


if __name__ == '__main__':
    unittest.main()
