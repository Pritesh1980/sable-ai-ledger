"""Tests for check_live.py: run with `python3 -m unittest -v`."""
import os
import shutil
import subprocess
import tempfile
import unittest

import check_live as cl

HERE = os.path.dirname(os.path.abspath(__file__))

# The first line of the live page as served on 2026-10-31 (version 12).
LIVE_HEAD = (
    '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-'
    'width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;box-sizing:bor'
    'der-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bott'
    'om,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;fon'
    't:14px -apple-system,BlinkMacSystemFont,sans-serif;background:#fff;color:#000}img{max-wi'
    'dth:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style></head><bod'
    'y>'
)


def wrap(page):
    """What publishing makes of a page."""
    return LIVE_HEAD + '\n' + page + '\n</body></html>'


def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Unwrap(unittest.TestCase):
    def test_strips_the_publish_wrapper(self):
        page = '<title>T</title>\n<p>hi</p>\n'
        self.assertEqual(cl.unwrap(wrap(page)), page)

    def test_tolerates_a_trailing_newline_after_the_wrapper(self):
        page = '<title>T</title>\n'
        self.assertEqual(cl.unwrap(wrap(page) + '\n'), page)

    def test_leaves_an_unwrapped_page_alone(self):
        page = '<title>T</title>\n<p>hi</p>\n'
        self.assertEqual(cl.unwrap(page), page)

    def test_real_wrapper_line_is_recognised(self):
        self.assertTrue(LIVE_HEAD.startswith(cl.WRAP_HEAD))
        self.assertTrue(LIVE_HEAD.endswith('<body>'))


class Check(unittest.TestCase):
    """Against a throwaway repo with three versions of the page."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        run(['git', 'init', '-q'], self.dir)
        run(['git', 'config', 'user.email', 't@example.com'], self.dir)
        run(['git', 'config', 'user.name', 'T'], self.dir)
        os.mkdir(os.path.join(self.dir, 'ledger'))
        self.versions = []
        for n in range(3):
            page = '<title>Ledger</title>\n<p>version {}</p>\n'.format(n)
            with open(os.path.join(self.dir, 'ledger', 'index.html'), 'w') as f:
                f.write(page)
            run(['git', 'add', '-A'], self.dir)
            run(['git', 'commit', '-q', '-m', 'v{}'.format(n)], self.dir)
            self.versions.append(page)
        # A data-only commit after the last page change.
        with open(os.path.join(self.dir, 'data.json'), 'w') as f:
            f.write('[]')
        run(['git', 'add', '-A'], self.dir)
        run(['git', 'commit', '-q', '-m', 'data'], self.dir)

    def test_an_older_commit_matches(self):
        code, msg = cl.check(wrap(self.versions[0]), self.dir)
        self.assertEqual(code, 0, msg)
        self.assertIn('2 commit(s) behind', msg)

    def test_the_current_page_matches(self):
        code, msg = cl.check(wrap(self.versions[2]), self.dir)
        self.assertEqual(code, 0, msg)
        self.assertIn('the current', msg)

    def test_one_changed_line_matches_nothing(self):
        edited = self.versions[1].replace('version 1', 'version 1, edited')
        code, msg = cl.check(wrap(edited), self.dir)
        self.assertEqual(code, 1, msg)
        self.assertIn('outside git', msg)

    def test_no_history_is_undecided(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        run(['git', 'init', '-q'], empty)
        code, _ = cl.check(wrap(self.versions[0]), empty)
        self.assertEqual(code, 2)

    def test_not_a_repo_is_undecided(self):
        plain = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, plain)
        code, _ = cl.check(wrap(self.versions[0]), os.path.join(plain, 'missing'))
        self.assertEqual(code, 2)

    def test_a_shallow_clone_without_a_match_is_undecided(self):
        shallow = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, shallow)
        run(['git', 'clone', '-q', '--depth', '1', 'file://' + self.dir, shallow], HERE)
        code, msg = cl.check(wrap(self.versions[0]), shallow)
        self.assertEqual(code, 2, msg)
        self.assertIn('--unshallow', msg)


@unittest.skipUnless(
    subprocess.run(['git', 'cat-file', '-e', 'a05b54d^{commit}'], cwd=HERE,
                   stderr=subprocess.DEVNULL).returncode == 0,
    'needs the full ledger history')
class RealHistory(unittest.TestCase):
    def test_the_page_live_before_the_31_oct_catch_up_matches(self):
        # On 31 Oct the live page was a05b54d's ledger/index.html, wrapped. That
        # commit didn't touch the page, so the match is the commit that wrote it.
        old = subprocess.run(['git', 'show', 'a05b54d:ledger/index.html'], cwd=HERE,
                             check=True, stdout=subprocess.PIPE).stdout.decode('utf-8')
        code, msg = cl.check(wrap(old), HERE)
        self.assertEqual(code, 0, msg)
        self.assertIn('behind the repo', msg)


if __name__ == '__main__':
    unittest.main()
