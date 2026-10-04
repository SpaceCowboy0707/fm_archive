import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from src.sql_console import query, schema, EXAMPLES


class SQLConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'test.sqlite3'
        with sqlite3.connect(self.db) as c:
            c.executescript('CREATE TABLE analytics_snapshots(game_date,sha256,payload_json); CREATE TABLE snapshots(id,game_date,club_name); CREATE TABLE player_snapshots(snapshot_id,identity_key,visible_json); CREATE TABLE transfer_events(date,season,payload_json);')
            for day,goals in [('2035-12-01',2),('2036-02-11',5)]:
                row=dict(identity_key='p',player_name='Monga',period='2035/36',kind='overall',team_id=1,team_slot=0,goals=goals)
                c.execute('INSERT INTO analytics_snapshots VALUES(?,?,?)',(day,day,json.dumps({'season_stats':[row]})))
        c.close()

    def test_json_view_latest_and_schema(self):
        names={r['name'] for r in schema(self.db)}
        self.assertIn('v_season_latest',names)
        result=query('SELECT player_name,goals FROM v_season_latest',self.db)
        self.assertEqual(result['rows'],[['Monga',5]])
        self.assertEqual(len(query('SELECT * FROM v_season_stats',self.db)['rows']),2)

    def test_write_attach_and_extension_blocked(self):
        before=self.db.read_bytes()
        for sql in ['DELETE FROM analytics_snapshots','DROP TABLE snapshots',"ATTACH DATABASE ':memory:' AS other",'PRAGMA query_only=OFF',"SELECT load_extension('anything')",'SELECT 1; SELECT 2;', 'CREATE TEMP TABLE bad(x)']:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.Error):query(sql,self.db)
        self.assertEqual(self.db.read_bytes(),before)

    def test_bounds_and_query_errors(self):
        sql='WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000) SELECT * FROM n'
        result=query(sql,self.db,limit=5)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['rows']),5)
        with self.assertRaises(sqlite3.Error):query(sql,self.db,seconds=-1)
        with self.assertRaises(sqlite3.Error):query('SELECT missing_column FROM snapshots',self.db)

    pass  # Private integration fixture is intentionally not published.
