#!/usr/bin/env python3
"""Build the Sable AI-usage datasets from the logs on this Mac.

Reads Claude Code transcripts, Codex session logs, git history and GitHub (through `gh`), and writes one JSON file of row objects per
dashboard dataset to ./out. Python 3.8+, standard library only.

    python3 ingest.py

A "task" is a GitHub PR where one exists. Work committed straight to main is
grouped by the issue its commit message names, else by the commit itself.
Replies on a feature branch belong to that branch's PR. Replies on main belong
to the next commit or PR command in the same session (within 4 hours), or the
one just before (within 30 minutes); anything else counts as unattributed.
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser('~')
REPO = os.environ.get('SABLE_REPO', os.path.join(HOME, 'code', 'tattoo-app'))
REPO_SLUG = 'Pritesh1980/sable'
CLAUDE_DIR = os.environ.get(
    'CLAUDE_TRANSCRIPTS', os.path.join(HOME, '.claude', 'projects', '-Users-pritesh-code-tattoo-app'))
CODEX_DIRS = [os.path.join(HOME, '.codex', 'sessions'), os.path.join(HOME, '.codex', 'archived_sessions')]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
SINCE = '2026-05-01'

# Claude API list prices, USD per million tokens: (input, output, cache read).
# Cache writes cost 1.25x input for a 5-minute entry and 2x for a 1-hour entry.
# Source: the claude-api reference bundled with Claude Code, cached 2026-10-06.
PRICES_AS_OF = '2026-10-06'
PRICES = {
    'claude-opus-5-5': (4.0, 20.0, 0.20),
    'claude-opus-5': (5.0, 25.0, 0.50),
    'claude-opus-4-8': (5.0, 25.0, 0.50),
    'claude-sonnet-5-5': (2.0, 10.0, 0.20),
    'claude-sonnet-5': (2.0, 10.0, 0.20),
    'claude-haiku-4-5': (1.0, 5.0, 0.10),
}
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0

KINDS = ('input', 'cw5', 'cw1h', 'cache_read', 'output', 'thinking')
MAIN_BRANCHES = ('', 'main', 'master', 'HEAD', None)
AHEAD = timedelta(hours=4)
BEHIND = timedelta(minutes=30)
REBUILD_MIN = 50_000

TEST_RE = re.compile(r'\b(npm (run )?test\b|npm run test:\w+|npx vitest|vitest run|npx playwright test)')
FAIL_RE = re.compile(r'\b[1-9]\d* (failed|failing)\b')
REVIEW_RE = re.compile(r'(?P<codex>\bcodex\b[^|;&\n]*\bexec\b)|(?P<agy>\bagy\b[^|;&\n]*(--print|\s-p\b))')
COMMIT_RE = re.compile(r'\bgit\b[^|;&\n]*\bcommit\b(?!-)')
GH_PR_RE = re.compile(r'\bgh pr (?:merge|create|view|checks|edit|comment|review|ready|diff)\s+(\d+)')
PR_URL_RE = re.compile(r'github\.com/' + re.escape(REPO_SLUG) + r'/pull/(\d+)')
CONV_TYPES = {'feat', 'fix', 'refactor', 'test', 'docs', 'chore', 'perf', 'ci', 'build', 'style', 'revert'}
MACHINE_PREFIXES = ('<', 'This session is being continued', '[SYSTEM', 'Caveat:')


# ---------------------------------------------------------------- pure helpers

_FRACTION = re.compile(r'\.(\d+)')


def parse_ts(s):
    """ISO time with Z, offsets and any number of fractional digits -> aware datetime."""
    if not s:
        return None
    s = str(s).strip().replace('Z', '+00:00')
    s = _FRACTION.sub(lambda m: '.' + (m.group(1) + '000000')[:6], s, count=1)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def local_day(d):
    return d.astimezone().strftime('%Y-%m-%d')


def norm_model(m):
    if not m:
        return 'unknown'
    m = m.split('[')[0]
    return re.sub(r'-\d{8}$', '', m)


def zero():
    return dict.fromkeys(KINDS, 0)


def add(acc, u):
    for k in KINDS:
        acc[k] += u.get(k, 0)
    return acc


def context(u):
    return u['input'] + u['cw5'] + u['cw1h'] + u['cache_read']


def cost(model, u):
    p = PRICES.get(norm_model(model))
    if not p:
        return None
    pin, pout, pcr = p
    return (u['input'] * pin + u['cw5'] * pin * CACHE_WRITE_5M + u['cw1h'] * pin * CACHE_WRITE_1H
            + u['cache_read'] * pcr + u['output'] * pout) / 1e6


def usage_of(u):
    u = u or {}
    written = u.get('cache_creation_input_tokens') or 0
    split = u.get('cache_creation') or {}
    cw1h = split.get('ephemeral_1h_input_tokens') or 0
    cw5 = split.get('ephemeral_5m_input_tokens')
    if cw5 is None:
        cw5 = max(0, written - cw1h)
    return dict(
        input=u.get('input_tokens') or 0, cw5=cw5, cw1h=cw1h,
        cache_read=u.get('cache_read_input_tokens') or 0,
        output=u.get('output_tokens') or 0,
        thinking=(u.get('output_tokens_details') or {}).get('thinking_tokens') or 0)


def merge_usage(a, b):
    """One message is logged once per content block; keep the fullest count of each kind."""
    return {k: max(a.get(k, 0), b.get(k, 0)) for k in KINDS}


def is_human_prompt(d):
    if d.get('type') != 'user' or d.get('isSidechain') or d.get('isMeta'):
        return False
    origin = d.get('origin')
    if isinstance(origin, dict) and origin.get('kind'):
        return origin['kind'] == 'human'
    if d.get('promptSource') == 'system':
        return False
    c = (d.get('message') or {}).get('content')
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
            return False
        c = ' '.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
    text = (c or '').lstrip()
    return bool(text) and not text.startswith(MACHINE_PREFIXES)


CODEX_KEYS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
              'output_tokens', 'reasoning_output_tokens')


def codex_step(prev, total):
    """Codex logs running totals; return (new running total, this call's usage or None)."""
    cur = {k: total.get(k) or 0 for k in CODEX_KEYS}
    if prev is None or any(cur[k] < prev[k] for k in CODEX_KEYS):
        d = cur  # first call, or a fresh context after a reset
    else:
        d = {k: cur[k] - prev[k] for k in CODEX_KEYS}
    if not any(d.values()):
        return cur, None
    cached, written = d['cached_input_tokens'], d['cache_write_input_tokens']
    return cur, dict(input=max(0, d['input_tokens'] - cached - written), cw5=written, cw1h=0,
                     cache_read=cached, output=d['output_tokens'], thinking=d['reasoning_output_tokens'])


def codex_deltas(totals):
    out, prev = [], None
    for total in totals:
        prev, d = codex_step(prev, total)
        if d:
            out.append(d)
    return out


def codex_role(meta):
    src = meta.get('source')
    sub = src.get('subagent') if isinstance(src, dict) else None
    if meta.get('thread_source') == 'guardian_review' or (isinstance(sub, dict) and sub.get('other') == 'guardian'):
        return 'auto-review'
    if meta.get('originator') == 'codex_exec':
        return 'review'
    return 'agent'


def branch_index(prs):
    idx = defaultdict(list)
    for p in prs:
        idx[p['headRefName']].append(p)
    for v in idx.values():
        v.sort(key=lambda p: p['createdAt'])
    return idx


def pr_for_branch(idx, branch, at):
    """The PR on this branch that was still open (or closed within 12 hours) at `at`."""
    cands = idx.get(branch)
    if not cands:
        return None
    for p in cands:
        closed = parse_ts(p.get('closedAt') or p.get('mergedAt'))
        if closed is None or closed >= at - timedelta(hours=12):
            return p['number']
    return cands[-1]['number']


def anchor_task(anchors, session, at):
    lst = anchors.get(session)
    if not lst:
        return None
    prev = None
    for ts, key in lst:
        if ts >= at:
            if ts - at <= AHEAD:
                return key
            break
        prev = (ts, key)
    if prev and at - prev[0] <= BEHIND:
        return prev[1]
    return None


def task_for_commit(subject, short, pr_numbers):
    m = re.search(r'\(#(\d+)\)\s*$', subject) or re.search(r'#(\d+)\b', subject)
    if m:
        n = int(m.group(1))
        return ('PR #%d' if n in pr_numbers else 'Issue #%d') % n
    return 'Commit ' + short


def match_commit(commits, at, used, window=timedelta(minutes=5)):
    best = None
    for c in commits:
        if c['sha'] in used:
            continue
        gap = abs(c['at'] - at)
        if gap <= window and (best is None or gap < best[0]):
            best = (gap, c)
    return best[1] if best else None


def conv_type(title):
    m = re.match(r'^\s*(\w+)(\([^)]*\))?!?:', title or '')
    if m and m.group(1).lower() in CONV_TYPES:
        return m.group(1).lower()
    return 'other'


def size_bucket(lines):
    if lines is None:
        return None
    if lines < 100:
        return 'S'
    if lines < 500:
        return 'M'
    if lines < 2000:
        return 'L'
    return 'XL'


def is_src(path):
    return (path.startswith('src/') and not path.startswith('src/test/')
            and '.test.' not in path and '.spec.' not in path)


def rework_count(task_files, shipped, main_commits, own=(), days=14):
    """Later `fix` commits on main, within `days`, that touch this task's source files."""
    src = {f for f in task_files if is_src(f)}
    if not src or shipped is None:
        return 0
    end = shipped + timedelta(days=days)
    n = 0
    for c in main_commits:
        if c['sha'] in own or not (shipped < c['at'] <= end):
            continue
        if conv_type(c['subject']) == 'fix' and src & set(c['files']):
            n += 1
    return n


ROLE_CODES = {'main': 0, 'agent': 0, 'subagent': 1, 'review': 2, 'auto-review': 3}


def build_waveform(replies, codex_rows, since):
    """Every Claude reply and Codex call since `since`, oldest first, as compact rows:
    [unix time, model index, tool (0 Claude, 1 Codex), context, output, cache written,
    rebuild 0/1, role (0 main/agent, 1 subagent, 2 review, 3 auto-review), task index or -1]."""
    calls = []
    for r in replies:
        if r['ts'] >= since:
            role = 'subagent' if r['sidechain'] else 'main'
            calls.append((r['ts'], 0, r['model'], r['usage'], 1 if r.get('rebuild') else 0, role, r.get('task')))
    for c in codex_rows:
        if c['ts'] >= since:
            calls.append((c['ts'], 1, c['model'], c['usage'], 0, c['role'], c.get('task')))
    calls.sort(key=lambda c: c[0])
    models, tasks, rows = {}, {}, []
    for ts, tool, model, u, rebuild, role, task in calls:
        m = models.setdefault(model, len(models))
        k = tasks.setdefault(task, len(tasks)) if task else -1
        rows.append([int(ts.timestamp()), m, tool, context(u), u['output'], u['cw5'] + u['cw1h'],
                     rebuild, ROLE_CODES.get(role, 0), k])
    return dict(fields=['t', 'model', 'tool', 'context', 'output', 'cache_write', 'rebuild', 'role', 'task'],
                models=list(models), tasks=list(tasks), rows=rows)


# ---------------------------------------------------------------- loaders


def zstd_binary():
    # Python 3.8 has no zstd module, so compressed logs go through the zstd tool.
    # launchd starts jobs with a bare PATH, hence the fixed fallbacks.
    for p in (shutil.which('zstd'), '/usr/local/bin/zstd', '/opt/homebrew/bin/zstd'):
        if p and os.path.exists(p):
            return p
    raise RuntimeError('Codex keeps older sessions as .jsonl.zst, and reading them needs the zstd tool.')


def iter_jsonl(path):
    if path.endswith('.zst'):
        proc = subprocess.Popen([zstd_binary(), '-dcq', path], stdout=subprocess.PIPE)
        f = io.TextIOWrapper(proc.stdout, encoding='utf-8', errors='replace')
    else:
        proc, f = None, open(path, encoding='utf-8', errors='replace')
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    finally:
        f.close()
        if proc:
            proc.wait()


def codex_files(dirs):
    """Every Codex session log under `dirs`, plain or zstd-compressed, each session once.
    Codex compresses older sessions in place and moves some to archived_sessions/."""
    found = {}
    for d in dirs:
        for pattern in ('*.jsonl', '*.jsonl.zst'):
            for path in glob.glob(os.path.join(d, '**', pattern), recursive=True):
                key = os.path.basename(path)[:-4] if path.endswith('.zst') else os.path.basename(path)
                if key not in found or found[key].endswith('.zst') and not path.endswith('.zst'):
                    found[key] = path
    return sorted(found.values())


def shrunk_days(old_daily, new_daily):
    """(day, tool, old tokens, new tokens) wherever a rebuild holds fewer tokens than the
    last snapshot did. Totals for a past day only ever grow, so a drop means logs went missing."""
    def totals(rows):
        t = Counter()
        for r in rows:
            t[(r['day'], r['tool'])] += sum(r.get(k) or 0 for k in KINDS)
        return t
    old, new = totals(old_daily), totals(new_daily)
    return [(day, tool, n, new.get((day, tool), 0)) for (day, tool), n in sorted(old.items())
            if new.get((day, tool), 0) < n]


def sh(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('%s failed: %s' % (' '.join(args[:3]), r.stderr.strip()[:300]))
    return r.stdout


def result_text(block, tur):
    if isinstance(tur, dict) and ('stdout' in tur or 'stderr' in tur):
        return '%s\n%s' % (tur.get('stdout') or '', tur.get('stderr') or '')
    c = block.get('content')
    if isinstance(c, list):
        return '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
    return c or ''


def load_claude():
    files = glob.glob(os.path.join(CLAUDE_DIR, '**', '*.jsonl'), recursive=True)
    replies, tool_uses, results = {}, {}, {}
    prompts, compactions, pr_links, titles, seen = [], [], [], {}, set()
    for path in files:
        for d in iter_jsonl(path):
            kind = d.get('type')
            uid = d.get('uuid')
            if kind == 'assistant':
                msg = d.get('message') or {}
                mid, model, ts = msg.get('id'), msg.get('model'), parse_ts(d.get('timestamp'))
                if not mid or not ts or model in (None, '<synthetic>'):
                    continue
                u = usage_of(msg.get('usage'))
                r = replies.get(mid)
                if r is None:
                    r = replies[mid] = dict(
                        id=mid, session=d.get('sessionId'), ts=ts, model=norm_model(model),
                        branch=d.get('gitBranch'), sidechain=bool(d.get('isSidechain')), usage=u, tools=0)
                else:
                    r['usage'] = merge_usage(r['usage'], u)
                for b in msg.get('content') or []:
                    if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('id') not in tool_uses:
                        inp = b.get('input') if isinstance(b.get('input'), dict) else {}
                        tool_uses[b['id']] = dict(reply=mid, name=b.get('name'), command=inp.get('command'))
                        r['tools'] += 1
            elif kind == 'user':
                if uid in seen:
                    continue
                seen.add(uid)
                if is_human_prompt(d):
                    prompts.append(dict(session=d.get('sessionId'), ts=parse_ts(d.get('timestamp'))))
                c = (d.get('message') or {}).get('content')
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get('type') == 'tool_result':
                            results[b.get('tool_use_id')] = dict(
                                ts=parse_ts(d.get('timestamp')), error=bool(b.get('is_error')),
                                text=result_text(b, d.get('toolUseResult'))[-20000:])
            elif kind == 'system' and d.get('subtype') == 'compact_boundary':
                if uid in seen:
                    continue
                seen.add(uid)
                compactions.append(dict(session=d.get('sessionId'), ts=parse_ts(d.get('timestamp'))))
            elif kind == 'pr-link' and d.get('prRepository') == REPO_SLUG:
                pr_links.append(dict(session=d.get('sessionId'), ts=parse_ts(d.get('timestamp')),
                                     pr=int(d.get('prNumber'))))
            elif kind == 'ai-title' and d.get('aiTitle'):
                titles[d.get('sessionId')] = d['aiTitle']
    return dict(replies=sorted(replies.values(), key=lambda r: r['ts']), tool_uses=tool_uses,
                results=results, prompts=[p for p in prompts if p['ts']], compactions=compactions,
                pr_links=pr_links, titles=titles, files=len(files))


def load_codex():
    rows, sessions = [], 0
    for path in codex_files(CODEX_DIRS):
        meta, model, prev, calls = None, None, None, []
        for d in iter_jsonl(path):
            kind, p = d.get('type'), d.get('payload') or {}
            if kind == 'session_meta' and meta is None:
                meta = p
            elif kind == 'turn_context':
                model = p.get('model') or model
            elif kind == 'event_msg' and p.get('type') == 'token_count':
                total = (p.get('info') or {}).get('total_token_usage')
                if total:
                    prev, u = codex_step(prev, total)
                    if u:
                        calls.append((parse_ts(d.get('timestamp')), model, u))
        if not meta:
            continue
        git = meta.get('git') or {}
        if not ((meta.get('cwd') or '').startswith(REPO) or REPO_SLUG in (git.get('repository_url') or '')):
            continue
        sessions += 1
        sid, role, branch = meta.get('id') or meta.get('session_id'), codex_role(meta), git.get('branch')
        for ts, m, u in calls:
            if ts:
                rows.append(dict(session=sid, ts=ts, model=norm_model(m), role=role, branch=branch, usage=u))
    return rows, sessions


def load_git():
    commits = []
    for line in sh(['git', 'log', '--all', '--since=' + SINCE, '--format=%H%x1f%h%x1f%cI%x1f%s'], REPO).splitlines():
        sha, short, at, subject = line.split('\x1f', 3)
        commits.append(dict(sha=sha, short=short, at=parse_ts(at), subject=subject))
    main = []
    out = sh(['git', 'log', 'origin/main', '--first-parent', '--since=' + SINCE, '--numstat',
              '--format=%x1e%H%x1f%h%x1f%cI%x1f%s'], REPO)
    for block in out.split('\x1e')[1:]:
        lines = block.strip('\n').split('\n')
        sha, short, at, subject = lines[0].split('\x1f', 3)
        files, changed = [], 0
        for ln in lines[1:]:
            parts = ln.split('\t')
            if len(parts) == 3:
                files.append(parts[2])
                changed += sum(int(x) for x in parts[:2] if x.isdigit())
        main.append(dict(sha=sha, short=short, at=parse_ts(at), subject=subject, files=files, lines=changed))
    return commits, main


def load_github():
    prs = json.loads(sh(['gh', 'pr', 'list', '--repo', REPO_SLUG, '--state', 'all', '--limit', '500', '--json',
                         'number,title,headRefName,createdAt,mergedAt,closedAt,state,additions,deletions,'
                         'changedFiles,closingIssuesReferences,url']))
    counts, cursor = {}, None
    owner, name = REPO_SLUG.split('/')
    while True:
        q = ('query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){'
             'pullRequests(first:100,after:$after){pageInfo{hasNextPage endCursor}'
             'nodes{number commits{totalCount}}}}}')
        args = ['gh', 'api', 'graphql', '-f', 'query=' + q, '-f', 'owner=' + owner, '-f', 'name=' + name]
        if cursor:
            args += ['-f', 'after=' + cursor]
        page = json.loads(sh(args))['data']['repository']['pullRequests']
        counts.update({n['number']: n['commits']['totalCount'] for n in page['nodes']})
        if not page['pageInfo']['hasNextPage']:
            break
        cursor = page['pageInfo']['endCursor']
    for p in prs:
        p['commit_count'] = counts.get(p['number'])
    issues = json.loads(sh(['gh', 'issue', 'list', '--repo', REPO_SLUG, '--state', 'all', '--limit', '500',
                            '--json', 'number,title,url,state']))
    runs = json.loads(sh(['gh', 'run', 'list', '--repo', REPO_SLUG, '--limit', '1000', '--json',
                          'headBranch,headSha,conclusion,event,workflowName,createdAt']))
    return prs, issues, runs


# ---------------------------------------------------------------- build


def ci_summary(runs):
    """CI cycles = distinct commits CI ran on; a cycle fails if any CI run on it failed."""
    by_sha = {}
    for r in sorted(runs, key=lambda r: r['createdAt']):
        s = by_sha.setdefault(r['headSha'], dict(at=r['createdAt'], ok=True, done=False))
        if r.get('conclusion') in ('failure', 'timed_out', 'startup_failure'):
            s['ok'] = False
        if r.get('conclusion'):
            s['done'] = True
    cycles = sorted((s for s in by_sha.values() if s['done']), key=lambda s: s['at'])
    if not cycles:
        return 0, 0, None
    return len(cycles), sum(1 for s in cycles if not s['ok']), cycles[0]['ok']


def build():
    claude = load_claude()
    codex_rows, codex_sessions = load_codex()
    all_commits, main_commits = load_git()
    prs, issues, runs = load_github()

    prs_by_num = {p['number']: p for p in prs}
    issues_by_num = {i['number']: i for i in issues}
    idx = branch_index(prs)
    ci_runs = [r for r in runs if r.get('workflowName') == 'CI']
    replies, results, tool_uses = claude['replies'], claude['results'], claude['tool_uses']
    reply_by_id = {r['id']: r for r in replies}

    # Anchors: moments a session committed, opened or acted on a PR.
    anchors = defaultdict(list)
    used, commit_cmds, tests, reviews = set(), [], [], []
    for tid, tu in tool_uses.items():
        cmd = tu.get('command')
        if not cmd:
            continue
        r = reply_by_id[tu['reply']]
        res = results.get(tid) or {}
        ts, text = res.get('ts') or r['ts'], res.get('text', '')
        if TEST_RE.search(cmd):
            tests.append(dict(reply=r['id'], failed=bool(res.get('error') or FAIL_RE.search(text))))
        m = REVIEW_RE.search(cmd)
        if m:
            reviews.append(dict(reply=r['id'], reviewer='codex' if m.group('codex') else 'agy'))
        if COMMIT_RE.search(cmd) and res and not res.get('error'):
            commit_cmds.append(dict(session=r['session'], ts=ts))
        for n in GH_PR_RE.findall(cmd):
            anchors[r['session']].append((ts, 'PR #' + n))
        if 'gh pr create' in cmd:
            for n in PR_URL_RE.findall(text):
                anchors[r['session']].append((ts, 'PR #' + n))
    pr_nums = set(prs_by_num)
    commit_task = {}
    for cc in sorted(commit_cmds, key=lambda c: c['ts']):
        c = match_commit(all_commits, cc['ts'], used)
        if c:
            used.add(c['sha'])
            key = task_for_commit(c['subject'], c['short'], pr_nums)
            commit_task[c['sha']] = key
            anchors[cc['session']].append((c['at'], key))
    first_link = set()
    for pl in sorted(claude['pr_links'], key=lambda p: p['ts'] or datetime.min.replace(tzinfo=timezone.utc)):
        if pl['ts'] and (pl['session'], pl['pr']) not in first_link:
            first_link.add((pl['session'], pl['pr']))
            anchors[pl['session']].append((pl['ts'], 'PR #%d' % pl['pr']))
    for v in anchors.values():
        v.sort(key=lambda a: a[0])

    def task_of(session, branch, at):
        if branch not in MAIN_BRANCHES:
            n = pr_for_branch(idx, branch, at)
            if n:
                return 'PR #%d' % n
        key = anchor_task(anchors, session, at)
        if key:
            return key
        if branch not in MAIN_BRANCHES and not re.match(r'^(worktree-|agent-)', branch):
            return 'Branch ' + branch
        return None

    for r in replies:
        r['task'] = task_of(r['session'], r['branch'], r['ts'])
        r['cost'] = cost(r['model'], r['usage'])
    for c in codex_rows:
        c['task'] = task_of(None, c['branch'], c['ts'])

    # Cache rebuilds: a main-thread reply, not a session's first, that rewrote most of its context.
    by_session = defaultdict(list)
    for r in replies:
        if not r['sidechain']:
            by_session[r['session']].append(r)
    for rs in by_session.values():
        for i, r in enumerate(rs):
            written = r['usage']['cw5'] + r['usage']['cw1h']
            r['rebuild'] = i > 0 and written >= REBUILD_MIN and written >= 0.5 * context(r['usage'])

    # Prompts belong to the task of the next main-thread reply in their session.
    prompt_task, prompts_by_session = Counter(), Counter()
    for p in claude['prompts']:
        prompts_by_session[p['session']] += 1
        nxt = next((r for r in by_session.get(p['session'], []) if r['ts'] >= p['ts']), None)
        if nxt and nxt['task']:
            prompt_task[nxt['task']] += 1

    # ---- daily
    daily = defaultdict(lambda: dict(replies=0, cost_usd=0.0, rebuilds=0, rebuild_tokens=0, **zero()))
    for r in replies:
        key = (local_day(r['ts']), 'Claude Code', r['model'], 'subagent' if r['sidechain'] else 'main', bool(r['task']))
        row = daily[key]
        row['replies'] += 1
        add(row, r['usage'])
        row['cost_usd'] += r['cost'] or 0
        if r.get('rebuild'):
            row['rebuilds'] += 1
            row['rebuild_tokens'] += r['usage']['cw5'] + r['usage']['cw1h']
    for c in codex_rows:
        row = daily[(local_day(c['ts']), 'Codex', c['model'], c['role'], bool(c['task']))]
        row['replies'] += 1
        add(row, c['usage'])
    daily_rows = []
    for (day, tool, model, role, attributed), row in sorted(daily.items()):
        row = dict(row)
        row['cost_usd'] = round(row['cost_usd'], 4) if tool == 'Claude Code' else None
        daily_rows.append(dict(day=day, tool=tool, model=model, role=role, attributed=attributed, **row))

    # ---- tasks
    acc = defaultdict(lambda: dict(
        usage=zero(), codex=zero(), codex_review=zero(), cost=0.0, out_by_model=Counter(), replies=0,
        subagent=0, tools=0, tests=0, test_fail=0, reviews=0, times=[], sessions=set()))
    for r in replies:
        if not r['task']:
            continue
        a = acc[r['task']]
        add(a['usage'], r['usage'])
        a['cost'] += r['cost'] or 0
        a['out_by_model'][r['model']] += r['usage']['output']
        a['replies'] += 1
        a['subagent'] += r['sidechain']
        a['tools'] += r['tools']
        a['times'].append(r['ts'])
        a['sessions'].add(r['session'])
    for c in codex_rows:
        if not c['task']:
            continue
        a = acc[c['task']]
        if c['role'] == 'review':
            add(a['codex_review'], c['usage'])
            continue
        add(a['codex'], c['usage'])
        if c['role'] == 'agent':
            a['out_by_model'][c['model']] += c['usage']['output']
            a['times'].append(c['ts'])
    for e in tests:
        task = reply_by_id[e['reply']]['task']
        if task:
            acc[task]['tests'] += 1
            acc[task]['test_fail'] += e['failed']
    for e in reviews:
        task = reply_by_id[e['reply']]['task']
        if task:
            acc[task]['reviews'] += 1

    main_by_task = defaultdict(list)
    for c in main_commits:
        main_by_task[task_for_commit(c['subject'], c['short'], pr_nums)].append(c)

    task_rows = []
    for key, a in acc.items():
        kind, _, ident = key.partition(' ')
        shas = {c['sha'] for c in main_by_task.get(key, [])}
        files = {f for c in main_by_task.get(key, []) for f in c['files']}
        title, url, state, lines, commits, shipped = ident, None, None, None, None, None
        task_ci = []
        if kind == 'PR':
            p = prs_by_num.get(int(ident[1:]))
            if p:
                title, url, state = p['title'], p['url'], p['state'].lower()
                lines = (p.get('additions') or 0) + (p.get('deletions') or 0)
                commits = p.get('commit_count')
                shipped = parse_ts(p.get('mergedAt'))
                start = parse_ts(p['createdAt']) - timedelta(days=2)
                end = parse_ts(p.get('closedAt') or p.get('mergedAt')) or datetime.now(timezone.utc)
                task_ci = [r for r in ci_runs if r['headBranch'] == p['headRefName']
                           and start <= parse_ts(r['createdAt']) <= end + timedelta(hours=1)]
                shas |= {r['headSha'] for r in task_ci}
        else:
            mc = main_by_task.get(key, [])
            if kind == 'Issue':
                i = issues_by_num.get(int(ident[1:]))
                title, url = (i['title'], i['url']) if i else (key, None)
            elif kind == 'Commit' and mc:
                title = mc[0]['subject']
            elif kind == 'Branch':
                title, state = ident, 'no PR'
            if mc:
                state = state or 'committed'
                lines = sum(c['lines'] for c in mc)
                commits = len(mc)
                shipped = max(c['at'] for c in mc)
                url = url or 'https://github.com/%s/commit/%s' % (REPO_SLUG, mc[-1]['sha'])
                task_ci = [r for r in ci_runs if r['headSha'] in shas]
            elif kind == 'Commit':
                title = next((c['subject'] for c in all_commits if c['short'] == ident), key)
                state = 'unmerged'
        cycles, cycle_fail, first_pass = ci_summary(task_ci)
        times = sorted(a['times'])
        active = sum(min((b - x).total_seconds(), 300) for x, b in zip(times, times[1:])) / 60
        agent_out = a['out_by_model']
        primary, share = None, None
        if agent_out and sum(agent_out.values()):
            primary, top = agent_out.most_common(1)[0]
            share = round(top / sum(agent_out.values()), 3)
        u = a['usage']
        task_rows.append(dict(
            task=key, title=title, kind=kind, url=url, type=conv_type(title) if kind != 'Branch' else
            (ident.split('/')[0] if ident.split('/')[0] in CONV_TYPES else 'other'),
            state=state, lines=lines, size=size_bucket(lines), commits=commits,
            started=local_day(times[0]) if times else None,
            shipped=local_day(shipped) if shipped else None,
            primary_model=primary, primary_share=share,
            models=', '.join(m for m, _ in agent_out.most_common()),
            cost_usd=round(a['cost'], 4), replies=a['replies'], subagent_replies=a['subagent'],
            prompts=prompt_task.get(key, 0), tool_calls=a['tools'],
            test_runs=a['tests'], test_failures=a['test_fail'], review_runs=a['reviews'],
            ci_cycles=cycles, ci_failures=cycle_fail, ci_first_pass=first_pass,
            rework=rework_count(files, shipped, main_commits, own=shas) if shipped else None,
            active_minutes=round(active, 1), sessions=len(a['sessions']),
            input=u['input'], cache_write=u['cw5'] + u['cw1h'], cache_read=u['cache_read'],
            output=u['output'], thinking=u['thinking'],
            avg_context=round(context(u) / a['replies']) if a['replies'] else None,
            codex_tokens=sum(a['codex'][k] for k in ('input', 'cw5', 'cache_read', 'output')),
            codex_review_tokens=sum(a['codex_review'][k] for k in ('input', 'cw5', 'cache_read', 'output')),
        ))
    task_rows.sort(key=lambda t: (t['started'] or '', t['task']), reverse=True)


    prices = [dict(model=m, input=p[0], output=p[1], cache_read=p[2], cache_write_5m=p[0] * CACHE_WRITE_5M,
                   cache_write_1h=p[0] * CACHE_WRITE_1H, as_of=PRICES_AS_OF) for m, p in PRICES.items()]

    os.makedirs(OUT, exist_ok=True)
    previous = os.path.join(OUT, 'daily.json')
    if os.path.exists(previous) and '--allow-shrink' not in sys.argv:
        with open(previous) as f:
            lost = shrunk_days(json.load(f), daily_rows)
        if lost:
            raise RuntimeError('Not writing out/: %d day(s) now hold fewer tokens than the last snapshot, '
                               'so some logs have gone missing. First: %s. Find the logs, or rerun with '
                               '--allow-shrink to accept the loss.' % (
                                   len(lost), ', '.join('%s %s %d->%d' % x for x in lost[:4])))
    datasets = dict(daily=daily_rows, tasks=task_rows, prices=prices)
    for name, rows in datasets.items():
        with open(os.path.join(OUT, name + '.json'), 'w') as f:
            json.dump(rows, f, separators=(',', ':'))
    # The last 30 days: the window both Claude Code and Codex logs fully cover.
    since = replies[-1]['ts'] - timedelta(days=30)
    waveform = build_waveform(replies, codex_rows, since)
    with open(os.path.join(OUT, 'waveform.json'), 'w') as f:
        json.dump(waveform, f, separators=(',', ':'))
    print('  out/waveform.json  %d calls since %s  %d KB' % (
        len(waveform['rows']), local_day(since), os.path.getsize(os.path.join(OUT, 'waveform.json')) // 1024))

    # ---- summary for the terminal
    total = sum(r['cost'] or 0 for r in replies)
    attributed = sum(r['cost'] or 0 for r in replies if r['task'])
    no_pr = Counter(r['branch'] for r in replies if r['task'] is None and r['branch'] not in MAIN_BRANCHES)
    print('Claude: %d files, %d replies, %s to %s, $%.2f API-equivalent, %.0f%% attributed to tasks' % (
        claude['files'], len(replies), local_day(replies[0]['ts']), local_day(replies[-1]['ts']),
        total, 100 * attributed / total if total else 0))
    print('Prompts: %d   Compactions: %d   Commit commands matched: %d/%d' % (
        len(claude['prompts']), len(claude['compactions']), len(commit_task), len(commit_cmds)))
    print('Codex: %d sessions, %d calls' % (codex_sessions, len(codex_rows)))
    print('Tasks: %d   Daily rows: %d' % (len(task_rows), len(daily_rows)))
    if no_pr:
        print('Unattributed branches:', ', '.join('%s (%d)' % kv for kv in no_pr.most_common(8)))
    for name, rows in datasets.items():
        print('  out/%s.json  %d rows  %d KB' % (name, len(rows), os.path.getsize(os.path.join(OUT, name + '.json')) // 1024))


if __name__ == '__main__':
    try:
        build()
    except RuntimeError as e:
        sys.exit(str(e))
