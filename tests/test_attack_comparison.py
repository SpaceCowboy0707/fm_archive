import unittest
from src.attack_comparison import build

class AttackTests(unittest.TestCase):
    def team(self,uid,players):
        return dict(uid=uid,roster=[dict(uid=i,name=str(i),natural_positions=pos) for i,mins,goals,pos in players],
                    stats=[dict(player_uid=i,player_name=str(i),kind='league',minutes=mins,goals=goals) for i,mins,goals,pos in players if mins is not None])
    def test_full_roster_ties_groups_and_missing(self):
        teams=[self.team(1,[(1,900,10,['DR','DC']),(2,0,0,['STC']),(3,None,0,['MC']),(4,90,5,['DR'])]),
               self.team(2,[(5,900,10,['DR']),(6,900,20,['DR'])])]
        r=build(teams,1,450)
        self.assertEqual(r['total'],4)
        p=r['rows'][0];self.assertEqual(p['per90'][0],1)
        b=next(x for x in p['benchmarks'] if x['group']=="Full-back")
        self.assertEqual(b['eligible_players'],3)
        self.assertEqual(b['rank_desc'][0],2)
        self.assertEqual(b['metric_sample_counts'][1],0)
        self.assertIsNone(b['percentile'][1])
        self.assertAlmostEqual(b['percentile'][0],33.3)
        self.assertEqual(r['rows'][1]['benchmarks'],[])
        self.assertIsNone(r['rows'][1]['per90'][0])
        self.assertEqual(r['rows'][2]['status'],'no_league_statistics')
        self.assertEqual(r['rows'][3]['status'],'below_min_minutes')
    def test_stat_only_and_duplicate_not_silently_ranked(self):
        t=self.team(1,[(1,900,10,['DR'])]);t['stats'].append(dict(t['stats'][0]))
        t['stats'].append(dict(player_uid=2,player_name='departed',kind='league',minutes=900,goals=3))
        r=build([t],1,450)
        self.assertEqual(r['rows'][0]['status'],'duplicate_statistics')
        self.assertEqual(r['rows'][0]['benchmarks'],[])
        self.assertFalse(r['rows'][1]['in_current_roster'])
        self.assertEqual(r['rows'][1]['benchmarks'],[])
