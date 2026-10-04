import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.conversations import SOURCE, load_conversation
from src.import_transcript import parse, import_file
from src.story_memory import rebuild, search
from src.evidence_gate import validate_answer


class MemoryTests(unittest.TestCase):
    pass  # Private integration fixture is intentionally not published.

    def test_memory_is_bounded_current_branch_and_source_linked(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'memory.sqlite3'
            messages=[dict(id=str(i),role='user' if i%2 else 'assistant',timestamp=None,
                text='Monga '+('memory '*1000),branch='CURRENT',ordinal=i) for i in range(9)]
            messages.append(dict(id='alternate',role='assistant',text='ALTERNATE_ONLY Monga',branch='ALTERNATE'))
            messages.append(dict(id='recap',role='assistant',text='RECAP_ONLY Monga',branch='CURRENT',metadata={'Content type':'reasoning_recap'}))
            messages.append(dict(id='image',role='user',timestamp=None,text='[STRUCTURED CONTENT -- JSON]\nIMAGE_METADATA_ONLY\n[END STRUCTURED CONTENT]\nVisible prose',branch='CURRENT'))
            data=dict(messages=messages,import_source=dict(sha256='test'))
            rebuild(data,db)
            events=[]
            result=search('Monga',db=db,on_event=events.append)
            self.assertEqual(len(result['rows']),6)
            self.assertIsNotNone(result['next_offset'])
            self.assertLess(len(json.dumps(result)),18000)
            for row in result['rows']:
                original=next(m for m in messages if m['id']==row['message_id'])
                self.assertEqual(row['text'],original['text'][row['start']:row['end']])
            self.assertFalse(search('ALTERNATE_ONLY',db=db)['rows'])
            self.assertFalse(search('RECAP_ONLY',db=db)['rows'])
            self.assertFalse(search('IMAGE_METADATA_ONLY',db=db)['rows'])
            self.assertTrue(search('Visible prose',db=db)['rows'])
            self.assertEqual(events[0]['details']['database'],'memory.sqlite3')
            self.assertFalse(search("zzunknown' OR 1=1--",db=db)['rows'])

    pass  # Private integration fixture is intentionally not published.

    pass  # Private integration fixture is intentionally not published.


if __name__=='__main__':unittest.main()
