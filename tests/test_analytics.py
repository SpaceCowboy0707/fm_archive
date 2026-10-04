import copy
import unittest
from src.analytics import (COUNTS, datasets, validate, season_rows, match_rows, aggregate_seasons,
                           aggregate_matches, aggregate_fixtures, project, MATCH_FIELDS)
from src.safe_export import ROOT


def stat(day,goals,minutes=90):
    return {'snapshot':{'date':day},'season_stats':[dict.fromkeys(COUNTS,0)|{
        'identity_key':'p1','player_name':'One','period':'2035/36','kind':'league','team_id':1,
        'club_uid':673,'club_name':'Leicester','team_slot':0,'goals':goals,'minutes':minutes,
        'starts':1,'rated_appearances':1,'average_rating':7.0}]}


class AnalyticsTests(unittest.TestCase):
    def test_cumulative_snapshots_replace_and_ratios_weight(self):
        older=stat('2035-12-01',2)
        newer=stat('2035-12-20',3,180)
        rows=season_rows([newer,older])
        self.assertEqual(len(rows),1)
        second=copy.deepcopy(rows[0]);second.update(identity_key='p2',goals=1,minutes=90,average_rating=9.0,rated_appearances=2)
        total=aggregate_seasons(rows+[second])[0]
        self.assertEqual(total['goals'],4)
        self.assertAlmostEqual(total['goals_per_90'],4*90/270)
        self.assertAlmostEqual(total['average_rating'],25/3)
        second['distance_km']=None
        self.assertIsNone(aggregate_seasons(rows+[second])[0]['distance_km'])

    def test_retained_match_detail_not_erased_and_new_attribution_used(self):
        row={key:None for key in MATCH_FIELDS}
        row.update(identity_key='p1',date='2035-11-01',competition_key='db:11',opponent_team_id=3,
                   own_club_uid=None,own_club_name=None,own_team_slot=None,attribution='unresolved',
                   has_stats=True,stats_in_range=True,goals=2,minutes=90,period='2035/36')
        newer={**row,'has_stats':False,'goals':None,'own_club_uid':673,'own_club_name':'Leicester','own_team_slot':0,'attribution':'matched_fixture'}
        rows=match_rows([{'snapshot':{'date':'2035-11-02'},'matches':[row]},
                         {'snapshot':{'date':'2035-12-01'},'matches':[newer]}])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['goals'],2)
        self.assertEqual(rows[0]['own_club_uid'],673)
        total=aggregate_matches(rows)[0]
        self.assertEqual(total['goals'],2)
        self.assertIsNone(total['assists'])
        self.assertEqual(total['assists_coverage'],0)

    def test_projection_never_reads_unlisted_attributes(self):
        class Guard:
            def __getattribute__(self,key):
                if key not in MATCH_FIELDS: raise AssertionError('Not an allowed field')
                return None
        self.assertEqual(set(project(Guard(),MATCH_FIELDS)),set(MATCH_FIELDS))

    def test_fixture_counts_do_not_treat_unknown_scores_as_zero(self):
        fixture={'period':'2035/36','competition_key':'db:11','home_club_uid':673,'away_club_uid':4,
                 'home_team_slot':0,'away_team_slot':0,'played':True,'home_goals':2,'away_goals':1}
        out=aggregate_fixtures([fixture,{**fixture,'home_goals':None}],673)[0]
        self.assertEqual(out["Retained played fixtures"],2)
        self.assertEqual(out["Fixtures with scores"],1)
        self.assertEqual(out["Wins"],1)
        self.assertEqual(out["Draws"],0)

    pass  # Private integration fixture is intentionally not published.

    pass  # Private integration fixture is intentionally not published.


if __name__=='__main__': unittest.main()
