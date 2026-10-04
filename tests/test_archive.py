import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import date
from src.safe_export import ROOT, ATTRIBUTES, project_player, check_payload
from src.archive import import_payload, snapshots, squad, history
from src.lore import load_lore


class GuardedRecord(SimpleNamespace):
    def __getattribute__(self, name):
        if name in {'ability', 'personality', 'raw_attributes', 'reputation', 'positions'}:
            raise AssertionError('Forbidden field access')
        return super().__getattribute__(name)


def fixture():
    player = GuardedRecord(uid=1, unique_id=2, name='Test Player', birth_date=date(2008,1,1),
        age=27, nation_id=1, height_cm=180, club_uid=673, club_name='Leicester', team_slot=0,
        natural_positions=('MC',), club_join_date=None, contract=None, on_loan=False,
        loan_parent_club_name=None, attributes=SimpleNamespace(**{key:10 for key in ATTRIBUTES}))
    return {'schema_version':1,
        'snapshot': {'sha256':'a'*64, 'filename':'test.fm', 'game_date':'2035-12-19',
                     'build':'test', 'fmsave_version':'0.5.4', 'exported_at':'test'},
        'club': {'uid':673,'name':'Leicester','manager':'Test'},
        'players':[project_player(player)],
        'validation':[{'reader':'players','status':'ok','record_count':1}]}


class ArchiveTests(unittest.TestCase):
    def test_projection_does_not_access_hidden_groups(self):
        check_payload(fixture())

    def test_unknown_and_hidden_fields_rejected_before_db_write(self):
        for path in ('player','attributes'):
            data = fixture()
            target = data['players'][0] if path == 'player' else data['players'][0]['attributes']
            target['ability' if path == 'player' else 'consistency'] = 'SYNTHETIC_BLOCKED'
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp)/'archive.db'
                with self.assertRaises(ValueError):
                    import_payload(data, db)
                self.assertFalse(db.exists())

    def test_idempotency_and_historical_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'archive.db'
            data = fixture()
            self.assertEqual(import_payload(data,db),(1,True))
            self.assertEqual(import_payload(data,db),(1,False))
            newer = copy.deepcopy(data)
            newer['snapshot'].update(sha256='b'*64,game_date='2036-01-01')
            newer['players'][0]['name']='Changed Name'
            self.assertEqual(import_payload(newer,db),(2,True))
            self.assertEqual(len(snapshots(db)),2)
            self.assertEqual(squad(1,db)[0]['name'],'Test Player')
            self.assertEqual(squad(2,db)[0]['name'],'Changed Name')
            self.assertEqual(len(history(data['players'][0]['identity_key'],db,through_date='2035-12-19')),1)

    def test_lore_requires_source_and_known_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'lore.json'
            entry = {'id':'test','level':'headcanon','title':'Test','text':'Fiction',
                     'source':'Manual example','season':'','player_keys':[],'player_names':[]}
            def write():
                path.write_text(json.dumps({'schema_version':1,'entries':[entry]}),encoding='utf-8')
            write()
            self.assertEqual(load_lore(path)[0]['level'],'headcanon')
            entry['source']=''
            write()
            with self.assertRaises(ValueError): load_lore(path)
            entry['source']='Example'
            entry['level']='probably_canon'
            write()
            with self.assertRaises(ValueError): load_lore(path)

    pass  # Private integration fixture is intentionally not published.


class InterfaceTests(unittest.TestCase):
    pass  # Private integration fixture is intentionally not published.


if __name__ == '__main__': unittest.main()
