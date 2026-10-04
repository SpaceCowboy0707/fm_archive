"""A clean checkout needs no personal conversation or database to start."""
import json
import tempfile
import unittest
from pathlib import Path

from src.conversations import load_conversation
from src.import_transcript import parse, import_file
from src.story_memory import rebuild, search
from src.evidence_gate import validate_answer


class PublicCheckoutTests(unittest.TestCase):
    def test_absent_conversation_is_an_empty_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            data=load_conversation(Path(folder)/'not-imported.json')
            self.assertEqual(data['messages'],[])
            self.assertFalse(data['coverage']['full_history_available'])

    def test_synthetic_transcript_import_is_idempotent_and_queryable(self):
        header='Conversation ID: 00000000-0000-0000-0000-000000000001\n'
        block=('='*90+'\nMESSAGE 1 / 1\nConversation title: Synthetic story\n'
               'Speaker: user\nCreated Unix: None\nMessage ID: synthetic-message\n'
               'Parent node: root\nNode ID: synthetic-message\nBranch: CURRENT\n'
               'Content type: text\n--- BEGIN ORIGINAL CONTENT ---\n'
               'Example captain welcomes a fictional teammate.\n--- END ORIGINAL CONTENT ---\n')
        raw=(header+block).encode()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'transcript.txt';source.write_bytes(raw)
            destination=root/'source.json'
            data=import_file(source,destination);before=destination.read_bytes()
            self.assertEqual(data['messages'][0]['text'],'Example captain welcomes a fictional teammate.')
            self.assertIsNone(data['messages'][0]['timestamp'])
            import_file(source,destination)
            self.assertEqual(destination.read_bytes(),before)
            db=root/'memory.sqlite3';rebuild(data,db)
            result=search('captain',db=db)
            self.assertEqual(result['rows'][0]['message_id'],'synthetic-message')
            document=dict(season='2035/36',comparison_player_ids=[],facts=[dict(query=0,path=['rows',0,'text'],value=data['messages'][0]['text'])],analysis='An attributed historical quote.')
            query=dict(name='story_memory',arguments={'query':'captain','offset':0},result=result)
            verdict=validate_answer(json.dumps(document),[query],'2036-03-04','What did we write?')
            self.assertTrue(verdict['passed'],verdict)
            self.assertIn('not verified game facts',verdict['verified_facts'][0])
        with self.assertRaises(ValueError):parse(raw.replace(b'MESSAGE 1 / 1',b'MESSAGE 1 / 2'))
