import unittest
from pathlib import Path
from service.addon_tools import INSTRUCTIONS_ADDON, TOOLS, read_guide


class GuideTests(unittest.TestCase):
    def test_local_guide_is_bounded_and_traversal_is_rejected(self):
        self.assertLessEqual(len(INSTRUCTIONS_ADDON), 1800)
        self.assertEqual(len(TOOLS), 10)
        for description in TOOLS.values():
            self.assertLessEqual(len(description), 2048)
        root = Path(__file__).resolve().parents[1] / 'service/guide/addon'
        for path in root.glob('*.md'):
            self.assertLessEqual(path.stat().st_size, 2048 if path.stem == 'index' else 8192)
        self.assertTrue(read_guide()['ok'])
        self.assertEqual(read_guide('../REMOTE-CONSTRUCTION-GUIDE')['error']['code'], 'NOT_FOUND')
