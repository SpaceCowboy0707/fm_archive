import copy
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace as NS
from datetime import date
from src import league_archive as la
from src.analytics import SEASON_FIELDS, COUNTS
from src.chat_tools import ArchiveTools


def payload(day,season,complete=False):
    teams=[]
    for uid in range(20):
        row=dict.fromkeys(SEASON_FIELDS)
        row.update(player_uid=uid,player_name='Player '+str(uid),kind='league',team_id=uid,club_uid=uid,club_name='Club '+str(uid),team_slot=0,minutes=3000,goals=10)
        teams.append(dict(club_uid=uid,club_unique_id=uid,club_name='Club '+str(uid),team_id=uid,in_premier=True,roster=[],stats=[row],standing=None,coverage=dict(roster_count=0,stats_by_kind={'league':1},league_player_count=1,league_stat_null_counts=dict.fromkeys(COUNTS,0),note='test')))
    return dict(sha256=day,game_date=day,season=season,competition_db_id=11,league_complete=complete,reset_detected=False,note='test',teams=teams)


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'test.sqlite3'

    def test_freeze_whole_snapshot_is_immutable_and_idempotent(self):
        for p in [payload('2035-04-01','2034/35'),payload('2035-05-30','2034/35',True),payload('2035-07-01','2035/36')]:la.store(p,self.db)
        self.assertFalse(la.store(p,self.db))
        la.store(payload('2035-06-01','2034/35',True),self.db)
        old=la.read_teams('2034/35',db=self.db)
        self.assertEqual(len(old),20)
        self.assertEqual({r['game_date'] for r in old},{'2035-05-30'})
        self.assertEqual(la.read_teams('2034/35',db=self.db,through_date='2035-08-01')[0]['game_date'],'2035-05-30')
        self.assertEqual(la.read_teams('2034/35',db=self.db,through_date='2035-04-02')[0]['game_date'],'2035-04-01')

    def test_incomplete_season_and_strict_fields(self):
        la.store(payload('2035-04-01','2034/35'),self.db)
        la.store(payload('2035-07-01','2035/36'),self.db)
        with closing(la.connection(self.db)) as con:
            row=con.execute('SELECT * FROM league_frozen_seasons').fetchone()
            self.assertEqual(row['league_complete'],0)
            self.assertIn("partial",row['note'])
        bad=payload('2035-08-01','2035/36');bad['teams'][0]['stats'][0]['potential_ability']=200
        with self.assertRaises(ValueError):la.store(bad,self.db)
        self.assertFalse(la.has_snapshot('2035-08-01',self.db))

    def test_reset_requires_broad_collapse(self):
        old=payload('2035-05-01','2034/35')['teams'];new=copy.deepcopy(old)
        new[0]['stats']=[]
        self.assertFalse(la.detect_reset(old,new))
        for t in new:t['stats']=[]
        self.assertTrue(la.detect_reset(old,new))

    def test_season_uses_fixtures_not_calendar_july(self):
        table=NS(competition_id=7,rows=[NS(team_id=n,played=0) for n in range(20)])
        fixtures=[NS(competition_id=7,season_start_year=2035,home_team_id=a,away_team_id=b,played=False,date=date(2035,8,1)) for a in range(20) for b in range(20) if a!=b]
        self.assertEqual(la.infer_season(table,fixtures,date(2035,6,25)),'2035/36')
        with self.assertRaises(ValueError):la.infer_season(table,fixtures[:-1],date(2035,6,25))

    def test_chat_cutoff_and_sql_trace(self):
        la.store(payload('2035-08-01','2035/36'),self.db)
        la.store(payload('2035-09-01','2035/36'),self.db)
        events=[];tools=ArchiveTools({'game_date':'2035-08-15'},self.db,events.append)
        args=dict(season='2035/36',club_name='Club 3',section='stats',kind='league',offset=0)
        result=tools.execute('league_team_data',args)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['rows'][0]['as_of'],'2035-08-01')
        self.assertEqual(result['rows'][0]['goals'],10)
        self.assertEqual(events[0]['kind'],'sqlite_read')
        self.assertEqual(events[-1]['kind'],'data_processed')

    def test_unmatched_club_lists_the_season_directory(self):
        la.store(payload('2035-08-01','2035/36'),self.db)
        tools=ArchiveTools({'game_date':'2035-08-15'},self.db)
        args=dict(season='2035/36',club_name='Leicester',section='teams',kind='league',offset=0)
        miss=tools.execute('league_team_data',args)
        self.assertEqual((miss['error_type'],miss['field']),('invalid_arguments','club_name'))
        self.assertIn('Club 3 (uid 3)',miss['expected']);self.assertEqual(len(miss['expected']),20)
        self.assertEqual(tools.execute('league_team_data',{**args,'club_name':'3'})['rows'][0]['club_name'],'Club 3')
        self.assertEqual(tools.execute('league_team_data',{**args,'season':'2030/31'})['field'],'season')

    def test_offseason_gap_is_recognised_only_when_clear(self):
        pairs=[(a,b) for a in range(20) for b in range(20) if a!=b]
        old=[NS(competition_id=7,season_start_year=2035,home_team_id=a,away_team_id=b,played=True,date=date(2036,5,1)) for a,b in pairs]
        new=[NS(competition_id=7,season_start_year=2036,home_team_id=a,away_team_id=b,played=False,date=date(2036,8,15+i%3)) for i,(a,b) in enumerate(pairs)]
        comps={7:11,9:67}
        self.assertEqual(la.offseason(comps,old+new,date(2036,7,6)),dict(finished_season='2035/36',next_season='2036/37',next_start='2036-08-15'))
        self.assertIsNone(la.offseason(comps,old+new,date(2036,8,15)))
        self.assertIsNone(la.offseason(comps,old[:-1]+new,date(2036,7,6)))
        self.assertIsNone(la.offseason({7:67},old+new,date(2036,7,6)))
        unfinished=old[:-1]+[NS(**{**vars(old[-1]),'played':False})]
        self.assertIsNone(la.offseason(comps,unfinished+new,date(2036,7,6)))

    def test_only_the_division_count_gate_is_tolerated(self):
        gate=lambda name,passed:NS(name=name,passed=passed)
        error=lambda *gates:NS(checks=(NS(reader='league_tables',gates=gates),))
        self.assertTrue(la.only_division_gate(error(gate('double_round_robin_divisions',False),gate('table_blocks_minimum',True))))
        self.assertFalse(la.only_division_gate(error(gate('double_round_robin_divisions',False),gate('table_blocks_minimum',False))))
        self.assertFalse(la.only_division_gate(error(gate('table_groups_resolved',False))))
        self.assertFalse(la.only_division_gate(NS(checks=(NS(reader='fixtures',gates=(gate('double_round_robin_divisions',False),)),))))

    def test_current_season_follows_the_latest_league_snapshot(self):
        self.assertIsNone(la.current_season('2036-09-21',self.db))
        la.store(payload('2036-06-18','2035/36',True),self.db);la.store(payload('2036-08-19','2036/37'),self.db)
        self.assertEqual(la.current_season('2036-09-21',self.db),'2036/37')
        self.assertEqual(la.current_season('2036-08-04',self.db),'2035/36')
        self.assertIsNone(la.current_season('2036-01-01',self.db))

    def test_team_totals_sum_players_and_rank_the_league(self):
        p=payload('2036-10-28','2036/37')
        for n,t in enumerate(p['teams']):
            t['standing']={**dict.fromkeys(la.STANDING_FIELDS,0),'club_uid':t['club_uid'],'team_id':t['team_id'],'played':9,'goals_for':11+n,'goals_against':n}
            t['stats'][0].update(expected_goals=5.0+n,tackles_completed=40,interceptions=None)
            keeper=dict(t['stats'][0],player_uid=100+n,player_name='Keeper '+str(n),goals=0,expected_goals=0.0,goals_allowed=n,shots_on_target_faced=3*n,expected_goals_prevented=0.5,tackles_completed=1)
            t['stats'].append(keeper)
        la.store(p,self.db)
        tools=ArchiveTools({'game_date':'2036-10-28'},self.db)
        args=dict(season='2036/37',club_name='Club 3',section='totals',kind='league',offset=0)
        row=tools.execute('league_team_data',args)['rows'][0]
        self.assertEqual((row['players'],row['keepers'],row['goals'],row['goals_for'],row['goals_not_credited_to_players']),(2,1,10,14,4))
        self.assertEqual((row['expected_goals'],row['expected_goals_per_match'],row['tackles_completed'],row['interceptions']),(8.0,0.89,41,None))
        self.assertEqual((row['goals_allowed'],row['shots_on_target_faced'],row['keeper_on_target_xg_faced']),(3,9,3.5))
        self.assertEqual((row['premier_league_rank']['expected_goals'],row['premier_league_rank']['goals_against']),(17,4))
        cup=tools.execute('league_team_data',{**args,'kind':'cup'})['rows'][0]
        self.assertEqual((cup['players'],cup['premier_league_rank']),(0,None));self.assertNotIn('played',cup)

    def test_offseason_skip_counts_as_done(self):
        save=Path(self.tmp.name)/'save.fm';save.write_bytes(b'save')
        digest=la.file_hash(save)
        self.assertFalse(la.stage_done(digest,self.db))
        gap=dict(finished_season='2035/36',next_season='2036/37',next_start='2036-08-15')
        self.assertEqual(la.record_offseason(save,digest,date(2036,7,6),gap,self.db)['status'],'offseason_skipped')
        self.assertTrue(la.stage_done(digest,self.db));self.assertFalse(la.has_snapshot(digest,self.db))
        self.assertEqual(la.export_snapshot(save,self.db)['next_start'],'2036-08-15')
        self.assertEqual(la.read_teams(db=self.db),[])

if __name__=='__main__':unittest.main()
