import unittest
from src.chat_routing import unsupported_request

class RoutingTests(unittest.TestCase):
    def test_weather_bypasses_archive(self):
        for q in ("What is tomorrow's weather","Will it rain in New York tomorrow",'weather tomorrow'):
            self.assertIsNotNone(unsupported_request(q))
    def test_fm_weather_and_analysis_stay_in_archive(self):
        for q in ("How does FM match weather affect play","Are there temperature records for this season","Why does Rothe run so much"):
            self.assertIsNone(unsupported_request(q))
