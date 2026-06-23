"""
tests/unit/test_fetch_layer.py
==============================
Priority-1 coverage for the KACE network fetch layer.

Covers every branch of:
  - scraper.fetch_config_list()  (cache hit, expired, API success/fail,
                                   HTML scrape, expired-cache fallback,
                                   total failure)
  - scraper.fetch_raw_config()   (cache hit, expired, network success/fail,
                                   no-cache total failure, empty download)

Strategy
--------
* Cache files use a real tempfile.TemporaryDirectory so that read/write
  logic is genuinely exercised (not mocked away).
* os.path.expanduser is patched to redirect "~" to the temp dir, keeping
  the production code paths intact.
* os.utime() controls cache-file mtime so fresh vs. expired branches are
  reached without mocking time.time().
* urllib.request.urlopen is patched to avoid real network calls.
  The _fake_response / _url_error helpers mirror the pattern in
  test_moonraker.py for consistency.
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.scraper import CACHE_EXPIRY_SECONDS


# ── Test helpers ──────────────────────────────────────────────────────────────

def _fake_response(raw_bytes: bytes):
    """Context-manager mock for urllib.request.urlopen that returns raw_bytes."""
    resp = MagicMock()
    resp.read.return_value = raw_bytes
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _url_error(reason: str = "Network unreachable"):
    """Return a urllib.error.URLError to simulate a network failure."""
    return urllib.error.URLError(reason)


def _github_api_payload(names):
    """Build a GitHub /contents JSON list with the given filenames."""
    return json.dumps([{"name": n} for n in names]).encode()


def _set_mtime(path: str, age_seconds: float):
    """Set a file's mtime to (now - age_seconds)."""
    t = time.time() - age_seconds
    os.utime(path, (t, t))


# ── fetch_config_list ─────────────────────────────────────────────────────────

class TestFetchConfigList(unittest.TestCase):
    """All branches of scraper.fetch_config_list()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = self._tmpdir.name
        # Redirect expanduser so "~/.kace_boards_cache.json" lands in tmpdir
        self._patch_exp = patch(
            'core.scraper.os.path.expanduser',
            side_effect=lambda p: p.replace('~', self._tmp),
        )
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
        self._tmpdir.cleanup()

    @property
    def _cache_path(self):
        return os.path.join(self._tmp, '.kace_boards_cache.json')

    # ── 1. Fresh cache hit ────────────────────────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_fresh_cache_hit_returns_cached_data_without_network(self, mock_urlopen):
        """A cache file younger than CACHE_EXPIRY_SECONDS is returned as-is;
        no network call is made."""
        cached = ['generic-bigtreetech-skr-v1.4.cfg', 'generic-creality-v4.2.2.cfg']
        with open(self._cache_path, 'w', encoding='utf-8') as f:
            json.dump(cached, f)
        _set_mtime(self._cache_path, age_seconds=100)  # 100 s old → fresh

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertEqual(result, cached)
        mock_urlopen.assert_not_called()

    # ── 2. Expired cache falls through to API ─────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_expired_cache_falls_through_to_github_api(self, mock_urlopen):
        """A cache older than CACHE_EXPIRY_SECONDS must be ignored;
        the function falls through to the GitHub API."""
        stale = ['generic-old-board.cfg']
        with open(self._cache_path, 'w', encoding='utf-8') as f:
            json.dump(stale, f)
        _set_mtime(self._cache_path, age_seconds=CACHE_EXPIRY_SECONDS + 3600)

        api_names = ['generic-bigtreetech-skr-v1.4.cfg', 'README.md']
        mock_urlopen.return_value = _fake_response(_github_api_payload(api_names))

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', result)
        self.assertNotIn('README.md', result)           # non-matching name filtered
        self.assertNotIn('generic-old-board.cfg', result)
        mock_urlopen.assert_called_once()

    # ── 3. GitHub API success ─────────────────────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_github_api_success_returns_filtered_configs(self, mock_urlopen):
        """GitHub API response is filtered to only generic-* and printer-* files."""
        names = [
            'generic-bigtreetech-skr-v1.4.cfg',
            'printer-creality-ender3.cfg',
            'README.md',
            'COPYING',
            'generic-creality-v4.2.7.cfg',
        ]
        mock_urlopen.return_value = _fake_response(_github_api_payload(names))

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', result)
        self.assertIn('printer-creality-ender3.cfg', result)
        self.assertIn('generic-creality-v4.2.7.cfg', result)
        self.assertNotIn('README.md', result)
        self.assertNotIn('COPYING', result)

    # ── 4. GitHub API success → cache written ─────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_github_api_success_writes_cache_for_next_call(self, mock_urlopen):
        """After a successful API fetch, the result must be written to disk so
        subsequent calls hit the fresh-cache branch."""
        names = ['generic-bigtreetech-skr-v1.4.cfg']
        mock_urlopen.return_value = _fake_response(_github_api_payload(names))

        from core.scraper import fetch_config_list
        fetch_config_list()

        self.assertTrue(os.path.exists(self._cache_path), "Cache file was not written after API success")
        with open(self._cache_path, 'r', encoding='utf-8') as f:
            on_disk = json.load(f)
        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', on_disk)

    # ── 5. API failure → HTML scrape (React JSON payload) ────────────────────

    @patch('urllib.request.urlopen')
    def test_api_failure_html_scrape_react_json_payload(self, mock_urlopen):
        """If the API call fails, fall back to scraping the GitHub HTML tree.
        The React JSON payload pattern ("name":"generic-*.cfg") must be matched."""
        html = b'''
        <html>
        <script>
        {"payload":{"tree":{"items":[
            {"name":"generic-bigtreetech-skr-v1.4.cfg"},
            {"name":"generic-creality-v4.2.2.cfg"},
            {"name":"README.md"}
        ]}}}
        </script>
        </html>
        '''
        # First call (API) raises; second call (HTML) succeeds
        mock_urlopen.side_effect = [_url_error(), _fake_response(html)]

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', result)
        self.assertIn('generic-creality-v4.2.2.cfg', result)
        self.assertNotIn('README.md', result)
        self.assertEqual(mock_urlopen.call_count, 2)

    # ── 6. API failure → HTML scrape (href pattern) ───────────────────────────

    @patch('urllib.request.urlopen')
    def test_api_failure_html_scrape_href_pattern(self, mock_urlopen):
        """The href regex pattern must extract configs from standard GitHub anchors."""
        html = (
            b'<a href="/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-v1.4.cfg">'
            b'<a href="/Klipper3d/klipper/blob/master/config/printer-creality-ender3.cfg">'
            b'<a href="/Klipper3d/klipper/blob/master/config/README.md">'
        )
        mock_urlopen.side_effect = [_url_error(), _fake_response(html)]

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', result)
        self.assertIn('printer-creality-ender3.cfg', result)
        self.assertNotIn('README.md', result)

    # ── 7. API + HTML both fail → expired cache fallback ─────────────────────

    @patch('urllib.request.urlopen')
    def test_api_and_html_failure_uses_expired_cache(self, mock_urlopen):
        """If both network paths fail, the function must fall back to the
        expired cache rather than returning the hardcoded list."""
        stale = ['generic-stale-board.cfg']
        with open(self._cache_path, 'w', encoding='utf-8') as f:
            json.dump(stale, f)
        _set_mtime(self._cache_path, age_seconds=CACHE_EXPIRY_SECONDS + 7200)

        # Both network calls fail
        mock_urlopen.side_effect = [_url_error(), _url_error()]

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        self.assertEqual(result, stale, "Should return expired cache when all network calls fail")

    # ── 8. Total failure → hardcoded fallback ────────────────────────────────

    @patch('urllib.request.urlopen')
    @patch('builtins.print')
    def test_total_failure_returns_hardcoded_fallback_and_warns(self, mock_print, mock_urlopen):
        """When no cache exists and all network calls fail, the function must
        return the hardcoded fallback list and print a user-visible warning."""
        # Ensure no cache file exists
        if os.path.exists(self._cache_path):
            os.remove(self._cache_path)

        mock_urlopen.side_effect = [_url_error(), _url_error()]

        from core.scraper import fetch_config_list
        result = fetch_config_list()

        # The hardcoded fallback always includes at least the two canonical entries
        self.assertIn('generic-bigtreetech-skr-v1.4.cfg', result)
        self.assertIn('generic-creality-v4.2.2.cfg', result)

        # A warning must be printed — user must know the list may be stale
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('Warning', printed)


# ── fetch_raw_config ──────────────────────────────────────────────────────────

class TestFetchRawConfig(unittest.TestCase):
    """All branches of scraper.fetch_raw_config()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = self._tmpdir.name
        self._patch_exp = patch(
            'core.scraper.os.path.expanduser',
            side_effect=lambda p: p.replace('~', self._tmp),
        )
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
        self._tmpdir.cleanup()

    @property
    def _cache_dir(self):
        return os.path.join(self._tmp, '.kace_configs_cache')

    def _write_cache(self, filename: str, content: str, age_seconds: float = 100):
        os.makedirs(self._cache_dir, exist_ok=True)
        p = os.path.join(self._cache_dir, filename)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        _set_mtime(p, age_seconds)
        return p

    # ── 1. Fresh cache hit ────────────────────────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_fresh_cache_hit_returns_content_without_network(self, mock_urlopen):
        """A cached config file within expiry must be returned with no network call."""
        expected = '[printer]\nkinematics: cartesian\n'
        self._write_cache('generic-bigtreetech-skr-v1.4.cfg', expected, age_seconds=60)

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertEqual(result, expected)
        mock_urlopen.assert_not_called()

    # ── 2. Expired cache falls through to network ─────────────────────────────

    @patch('urllib.request.urlopen')
    def test_expired_cache_falls_through_to_network(self, mock_urlopen):
        """A cache file older than CACHE_EXPIRY_SECONDS must be ignored."""
        stale = '[printer]\nkinematics: stale\n'
        fresh = '[printer]\nkinematics: cartesian\n'
        self._write_cache('generic-bigtreetech-skr-v1.4.cfg', stale,
                          age_seconds=CACHE_EXPIRY_SECONDS + 3600)

        mock_urlopen.return_value = _fake_response(fresh.encode())

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertIn('cartesian', result)
        self.assertNotIn('stale', result)
        mock_urlopen.assert_called_once()

    # ── 3. Network success writes cache ───────────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_network_success_writes_cache_file(self, mock_urlopen):
        """Successful download must be persisted so the next call is a cache hit."""
        content = '[stepper_x]\nstep_pin: P2.2\n'
        mock_urlopen.return_value = _fake_response(content.encode())

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertEqual(result, content)
        cache_path = os.path.join(self._cache_dir, 'generic-bigtreetech-skr-v1.4.cfg')
        self.assertTrue(os.path.exists(cache_path), "Cache file should have been written")
        with open(cache_path, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), content)

    # ── 4. Network failure → expired cache fallback ───────────────────────────

    @patch('urllib.request.urlopen')
    def test_network_failure_returns_expired_cache(self, mock_urlopen):
        """If the network call raises, the function must return the expired cache
        rather than an empty string."""
        stale_content = '[printer]\nkinematics: cartesian\n'
        self._write_cache('generic-bigtreetech-skr-v1.4.cfg', stale_content,
                          age_seconds=CACHE_EXPIRY_SECONDS + 7200)

        mock_urlopen.side_effect = _url_error()

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertEqual(result, stale_content)

    # ── 5. Total failure (no cache, no network) → empty string ───────────────

    @patch('urllib.request.urlopen')
    @patch('builtins.print')
    def test_total_failure_returns_empty_string_and_warns(self, mock_print, mock_urlopen):
        """If there is no cache and the network fails, return '' and warn the user."""
        mock_urlopen.side_effect = _url_error()

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-nonexistent-board.cfg')

        self.assertEqual(result, '', "Total failure should return empty string")
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('Warning', printed)

    # ── 6. Malformed / empty download ────────────────────────────────────────

    @patch('urllib.request.urlopen')
    def test_empty_download_returns_empty_string(self, mock_urlopen):
        """A successful HTTP response that delivers zero bytes must return ''
        (not raise) — the caller (kace.py) guards for falsy return values."""
        mock_urlopen.return_value = _fake_response(b'')

        from core.scraper import fetch_raw_config
        result = fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertEqual(result, '')

    # ── 7. Cache directory auto-created on first use ─────────────────────────

    @patch('urllib.request.urlopen')
    def test_cache_directory_is_created_if_missing(self, mock_urlopen):
        """On first use, ~/.kace_configs_cache/ must be created automatically."""
        self.assertFalse(os.path.exists(self._cache_dir))
        mock_urlopen.return_value = _fake_response(b'[printer]\n')

        from core.scraper import fetch_raw_config
        fetch_raw_config('generic-bigtreetech-skr-v1.4.cfg')

        self.assertTrue(os.path.isdir(self._cache_dir),
                        "Cache directory must be created on first fetch")


if __name__ == '__main__':
    unittest.main()
