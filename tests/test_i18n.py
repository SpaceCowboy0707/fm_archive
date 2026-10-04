import unittest,json
from pathlib import Path
from src.i18n import translate,INPUT_ALIASES
from src.chat_routing import unsupported_request
from src.evidence_gate import validate_answer
from src.safe_export import ROOT
from streamlit.testing.v1 import AppTest

class LocalizationTests(unittest.TestCase):
    def test_messages_and_originals_are_separate(self):
        self.assertEqual(translate('Current squad'),'Current squad')
        self.assertEqual(translate('Current squad','zh-CN'),'\u5f53\u524d\u540d\u5355')
        self.assertEqual(translate('A private original story','zh-CN'),'A private original story')
        self.assertIn('13',translate('Loaded 13 available models; select one under Chat model.','zh-CN'))
    def test_bilingual_weather_and_game_scope(self):
        for question in ('Will it rain tomorrow?', '\u660e\u5929\u5929\u6c14\u600e\u4e48\u6837'):
            self.assertIsNotNone(unsupported_request(question))
        for question in ('FM match weather', '\u8fd9\u4e2a\u8d5b\u5b63\u7684\u6c14\u6e29\u8bb0\u5f55'):
            self.assertIsNone(unsupported_request(question))
        self.assertIn('\u83b1\u65af\u7279',INPUT_ALIASES['club_aliases'])
    def test_both_languages_keep_title_gate(self):
        raw=json.dumps(dict(season='2035/36',comparison_player_ids=[],facts=[],analysis='Unverified title assertion'))
        for question in ('Are we champions now?', '\u73b0\u5728\u51a0\u519b\u7a33\u4e86\u5427'):
            result=validate_answer(raw,[],'2036-03-04',question)
            self.assertFalse(result['passed'])
            self.assertIn('Title-race question lacks the programmatic points calculation',result['errors'])
    pass  # Private integration fixture is intentionally not published.
    def test_repository_product_source_is_english(self):
        import re
        for path in [ROOT/'app.py',* (ROOT/'src').glob('*.py')]:
            if path.name=='i18n.py':continue
            # The language selector's native label is the sole intentional UI exception.
            text=path.read_text(encoding='utf-8').replace('\u4e2d\u6587','')
            self.assertIsNone(re.search('[\u4e00-\u9fff]',text),str(path))
