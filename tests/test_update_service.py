import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop' / 'common'))
from update_service import VERSION, UpdateInfo, check_for_updates, parse_version, resolve_release

BASE = {'tag_name':'v0.7.0',
        'html_url':'https://github.com/haseebgb92/AURA-Download-Manager/releases/tag/v0.7.0',
        'draft':False,'prerelease':False,'body':'Release notes'}

class ReleaseTests(unittest.TestCase):
    def test_versions(self):
        self.assertLess(parse_version('0.6.0'),parse_version('v0.7.0'))
        with self.assertRaises(ValueError):parse_version('not-a-version')
    def test_newer_release(self):
        release=resolve_release(BASE)
        self.assertEqual(release.state,'available')
        self.assertEqual(release.version,'0.7.0')
    def test_current_release(self):
        self.assertEqual(resolve_release({**BASE,'tag_name':'v0.6.2'}).state,'current')
    def test_block_untrusted_url(self):
        self.assertEqual(resolve_release({**BASE,'html_url':'https://evil.example/trap'}).url,
                         'https://github.com/haseebgb92/AURA-Download-Manager/releases')
    def test_reject_unexpected_json(self):
        with self.assertRaises(ValueError):resolve_release({'tag_name':'invalid'})
    def test_no_published_release(self):
        error=HTTPError('https://api.github.com',404,'Not Found',{},None)
        with mock.patch('urllib.request.urlopen',side_effect=error):
            self.assertEqual(check_for_updates().state,'unpublished')
    def test_version_constant(self):
        self.assertEqual(VERSION,'0.6.2')

if __name__=='__main__':unittest.main()
