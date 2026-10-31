"""Is the live ledger page just an older commit of ledger/index.html?

Usage: python3 check_live.py <saved-live.html>

The daily routine runs this when a publish is refused. Exit codes:
  0  the live page equals a past commit of ledger/index.html: safe to overwrite
  1  it matches no commit, so someone edited the live page outside git: stop
  2  can't tell (no git history, shallow clone, unreadable file): stop

Standard library only, Python 3.8+.
"""
import subprocess
import sys

PAGE = 'ledger/index.html'
# Publishing wraps the page: one line of document head before it, and the
# closing tags after it.
WRAP_HEAD = '<!doctype html><html><head><meta charset=utf8>'
WRAP_TAIL = '\n</body></html>'


def unwrap(html):
    """The page source as committed, without the wrapper publishing adds."""
    first, sep, rest = html.partition('\n')
    if not (sep and first.startswith(WRAP_HEAD) and first.endswith('<body>')):
        return html
    if rest.endswith(WRAP_TAIL + '\n'):
        rest = rest[:-1]
    return rest[:-len(WRAP_TAIL)] if rest.endswith(WRAP_TAIL) else rest


def git(args, cwd):
    return subprocess.run(['git'] + args, cwd=cwd, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def page_history(cwd='.'):
    """(commit, source) for each commit that changed the page, newest first."""
    commits = git(['log', '--format=%H', '--', PAGE], cwd).decode().split()
    return [(c, git(['show', '{}:{}'.format(c, PAGE)], cwd).decode('utf-8')) for c in commits]


def is_shallow(cwd='.'):
    return git(['rev-parse', '--is-shallow-repository'], cwd).decode().strip() == 'true'


def check(live_html, cwd='.'):
    """Return (exit code, message)."""
    page = unwrap(live_html)
    try:
        history = page_history(cwd)
    except (OSError, subprocess.CalledProcessError) as e:
        return 2, 'cannot read git history of {}: {}'.format(PAGE, e)
    if not history:
        return 2, 'no commits of {} in this clone'.format(PAGE)
    for i, (commit, source) in enumerate(history):
        if source == page:
            if i == 0:
                return 0, 'live page matches {}, the current {}'.format(commit[:7], PAGE)
            return 0, 'live page matches {}, {} commit(s) behind the repo'.format(commit[:7], i)
    if is_shallow(cwd):
        return 2, ('live page matches none of the {} commits in this shallow clone; '
                   'run `git fetch --unshallow` and try again'.format(len(history)))
    return 1, ('live page matches none of the {} commits of {}: '
               'it was edited outside git'.format(len(history), PAGE))


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2])
        return 2
    try:
        with open(argv[1], encoding='utf-8') as f:
            live = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print('cannot read {}: {}'.format(argv[1], e))
        return 2
    code, message = check(live)
    print(message)
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv))
