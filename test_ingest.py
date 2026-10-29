"""Unit tests for the pure parts of ingest.py: run with `python3 -m unittest -v`."""
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import ingest as ing


def t(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class Cost(unittest.TestCase):
    def test_normalises_model_ids(self):
        self.assertEqual(ing.norm_model('claude-haiku-4-5-20251001'), 'claude-haiku-4-5')
        self.assertEqual(ing.norm_model('claude-opus-5-5[1m]'), 'claude-opus-5-5')
        self.assertEqual(ing.norm_model('gpt-6-sol'), 'gpt-6-sol')

    def test_cost_prices_each_token_kind_at_its_own_rate(self):
        m = 1_000_000
        u = dict(input=m, cw5=m, cw1h=m, cache_read=m, output=m, thinking=0)
        # Opus 5.5: input 4 + 5-min write 5 + 1-hour write 8 + read 0.20 + output 20
        self.assertAlmostEqual(ing.cost('claude-opus-5-5', u), 37.20)
        # Sonnet 5.5: 2 + 2.5 + 4 + 0.20 + 10
        self.assertAlmostEqual(ing.cost('claude-sonnet-5-5', u), 18.70)

    def test_unknown_model_has_no_cost(self):
        self.assertIsNone(ing.cost('gpt-6-sol', dict(input=1, cw5=0, cw1h=0, cache_read=0, output=1)))


class Usage(unittest.TestCase):
    def test_splits_cache_writes_by_ttl(self):
        u = ing.usage_of({
            'input_tokens': 2, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 5,
            'output_tokens': 7, 'output_tokens_details': {'thinking_tokens': 3},
            'cache_creation': {'ephemeral_5m_input_tokens': 4, 'ephemeral_1h_input_tokens': 6},
        })
        self.assertEqual(u, dict(input=2, cw5=4, cw1h=6, cache_read=5, output=7, thinking=3))

    def test_writes_without_ttl_breakdown_count_as_5_minute(self):
        u = ing.usage_of({'input_tokens': 1, 'cache_creation_input_tokens': 9, 'output_tokens': 1})
        self.assertEqual((u['cw5'], u['cw1h']), (9, 0))

    def test_repeated_lines_of_one_message_merge_by_max(self):
        a = dict(input=2, cw5=10, cw1h=0, cache_read=5, output=1, thinking=0)
        b = dict(input=2, cw5=10, cw1h=0, cache_read=5, output=40, thinking=12)
        self.assertEqual(ing.merge_usage(a, b)['output'], 40)
        self.assertEqual(ing.merge_usage(a, b)['thinking'], 12)


class Prompts(unittest.TestCase):
    def ev(self, content, **kw):
        return {'type': 'user', 'message': {'content': content}, **kw}

    def test_typed_prompt_counts(self):
        self.assertTrue(ing.is_human_prompt(self.ev('fix the header', origin={'kind': 'human'})))
        self.assertTrue(ing.is_human_prompt(self.ev('all sounds good')))

    def test_machine_messages_do_not_count(self):
        self.assertFalse(ing.is_human_prompt(self.ev([{'type': 'tool_result', 'tool_use_id': 'x'}])))
        self.assertFalse(ing.is_human_prompt(self.ev('<system-reminder>hi</system-reminder>')))
        self.assertFalse(ing.is_human_prompt(self.ev('done', origin={'kind': 'task-notification'})))
        self.assertFalse(ing.is_human_prompt(self.ev('You are a reviewer', isSidechain=True)))
        self.assertFalse(ing.is_human_prompt(self.ev('This session is being continued from a previous one')))


class Codex(unittest.TestCase):
    def test_deltas_from_cumulative_totals_including_a_reset(self):
        totals = [
            {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 10, 'reasoning_output_tokens': 2},
            {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 10, 'reasoning_output_tokens': 2},
            {'input_tokens': 250, 'cached_input_tokens': 200, 'output_tokens': 30, 'reasoning_output_tokens': 5},
            {'input_tokens': 40, 'cached_input_tokens': 0, 'output_tokens': 5, 'reasoning_output_tokens': 0},
        ]
        d = ing.codex_deltas(totals)
        self.assertEqual(len(d), 3)  # the repeated total adds nothing
        self.assertEqual(d[0], dict(input=40, cw5=0, cw1h=0, cache_read=60, output=10, thinking=2))
        self.assertEqual(d[1], dict(input=10, cw5=0, cw1h=0, cache_read=140, output=20, thinking=3))
        self.assertEqual(d[2]['input'], 40)  # a drop means a fresh context: take the total as is

    def test_finds_plain_and_compressed_logs_in_every_folder_once(self):
        with tempfile.TemporaryDirectory() as root:
            live, archived = os.path.join(root, 'sessions', '2026', '07'), os.path.join(root, 'archived_sessions')
            os.makedirs(live), os.makedirs(archived)
            for folder, name in [(live, 'rollout-a.jsonl'), (live, 'rollout-b.jsonl.zst'),
                                 (archived, 'rollout-c.jsonl.zst'), (archived, 'rollout-a.jsonl.zst'),
                                 (live, 'notes.txt')]:
                open(os.path.join(folder, name), 'w').close()
            found = ing.codex_files([os.path.join(root, 'sessions'), archived])
            names = sorted(os.path.basename(p) for p in found)
            # rollout-a is in both folders: the plain copy wins, and it is read once
            self.assertEqual(names, ['rollout-a.jsonl', 'rollout-b.jsonl.zst', 'rollout-c.jsonl.zst'])

    @unittest.skipUnless(shutil.which('zstd'), 'zstd not installed')
    def test_reads_zstd_compressed_logs(self):
        with tempfile.TemporaryDirectory() as root:
            plain = os.path.join(root, 'rollout.jsonl')
            with open(plain, 'w') as f:
                f.write('{"type": "session_meta"}\nnot json\n\n{"type": "turn_context"}\n')
            subprocess.run(['zstd', '-q', '--rm', plain], check=True)
            rows = list(ing.iter_jsonl(plain + '.zst'))
            self.assertEqual([r['type'] for r in rows], ['session_meta', 'turn_context'])

    def test_roles(self):
        self.assertEqual(ing.codex_role({'originator': 'codex_exec', 'source': 'exec'}), 'review')
        self.assertEqual(ing.codex_role({'thread_source': 'guardian_review', 'source': {'subagent': {'other': 'guardian'}}}), 'auto-review')
        self.assertEqual(ing.codex_role({'originator': 'Codex Desktop', 'source': 'vscode'}), 'agent')


class Attribution(unittest.TestCase):
    def test_branch_maps_to_the_pr_open_at_reply_time(self):
        prs = [
            {'number': 10, 'headRefName': 'feat/x', 'createdAt': '2026-09-01T00:00:00Z', 'closedAt': '2026-09-05T00:00:00Z'},
            {'number': 20, 'headRefName': 'feat/x', 'createdAt': '2026-10-01T00:00:00Z', 'closedAt': None},
        ]
        idx = ing.branch_index(prs)
        self.assertEqual(ing.pr_for_branch(idx, 'feat/x', t('2026-09-03T00:00:00')), 10)
        self.assertEqual(ing.pr_for_branch(idx, 'feat/x', t('2026-09-20T00:00:00')), 20)
        self.assertIsNone(ing.pr_for_branch(idx, 'feat/y', t('2026-09-20T00:00:00')))

    def test_main_branch_reply_goes_to_the_next_anchor_in_its_session(self):
        anchors = {'s1': [(t('2026-10-01T10:30:00'), 'PR #5'), (t('2026-10-01T12:00:00'), 'Commit abc1234')]}
        at = lambda hm: ing.anchor_task(anchors, 's1', t(f'2026-10-01T{hm}:00'))
        self.assertEqual(at('10:00'), 'PR #5')
        self.assertEqual(at('11:00'), 'Commit abc1234')
        self.assertEqual(at('12:20'), 'Commit abc1234')  # just after: looks back 30 minutes
        self.assertIsNone(at('16:00'))
        self.assertIsNone(ing.anchor_task(anchors, 's2', t('2026-10-01T10:00:00')))

    def test_commit_subject_names_its_task(self):
        prs = {87}
        self.assertEqual(ing.task_for_commit('feat(wall): rank rail (#87)', 'e0c490e', prs), 'PR #87')
        # a trailing (#N) that is not a PR closes an issue from a direct commit
        self.assertEqual(ing.task_for_commit('feat(wall): rank rail (#88)', 'e0c490e', prs), 'Issue #88')
        self.assertEqual(ing.task_for_commit('fix(infra): pin base (refs #6)', 'f02212e', prs), 'Issue #6')
        self.assertEqual(ing.task_for_commit('docs: correct install route', 'b89e19c', prs), 'Commit b89e19c')

    def test_commit_command_matches_the_nearest_commit_in_time(self):
        commits = [
            {'sha': 'a' * 40, 'at': t('2026-10-01T10:00:00')},
            {'sha': 'b' * 40, 'at': t('2026-10-01T10:02:00')},
        ]
        self.assertEqual(ing.match_commit(commits, t('2026-10-01T10:01:50'), set())['sha'], 'b' * 40)
        self.assertEqual(ing.match_commit(commits, t('2026-10-01T10:01:50'), {'b' * 40})['sha'], 'a' * 40)
        self.assertIsNone(ing.match_commit(commits, t('2026-10-01T11:00:00'), set()))


class Reviews(unittest.TestCase):
    def test_reviewer_runs_count(self):
        runs = {
            'codex exec --sandbox read-only "Review this diff"': 'codex',
            '/Applications/ChatGPT.app/Contents/Resources/codex exec --sandbox read-only "$(cat p.txt)" > out.txt 2>&1 < /dev/null': 'codex',
            'S=/tmp/x; cd $S && agy --print "$(cat agy.prompt)" > agy.out 2>&1 < /dev/null; echo "exit $?"': 'agy',
            'cd /tmp/x && (nohup agy --print "Review this PR" > a.out 2>&1 &)': 'agy',
            'SP=/tmp/x\ncodex exec --sandbox read-only "Review commit ac396a8"': 'codex',
            'timeout 900 codex exec -C /tmp/x "Review it"': 'codex',
            'git add -A && git commit -q -m "wip" && codex exec --sandbox read-only "Review it"': 'codex',
            'agy -p "Review the plan"': 'agy',
            "codex exec --sandbox read-only - <<'EOF'\nDon't modify files.\nEOF": 'codex',
        }
        for cmd, tool in runs.items():
            self.assertEqual(ing.review_tool(cmd), tool, cmd)

    def test_polls_and_mentions_do_not(self):
        cmds = [
            'pgrep -f "codex exec --skip-git-repo-check" >/dev/null && echo running || echo finished',
            'until ! pgrep -f "codex exec.*PR #130" >/dev/null && ! pgrep -f "agy --print" >/dev/null; do sleep 20; done',
            "ps aux | grep 'codex exec'",
            'pkill -f "codex exec"',
            'kill 48316 48314 2>/dev/null; sleep 1; pgrep -fl "codex exec" | head -3',
            'wc -c /tmp/codex-exec.out; tail -5 /tmp/agy--print.txt',
            "echo '- [Reviewer CLIs](x.md) — agy --print cannot run commands' >> MEMORY.md",
            'git commit -q -m "docs: run codex exec before merging"',
            "cat > notes.md <<'EOF'\ncodex exec --sandbox read-only \"x\"\nEOF\nls",
            'codex --version',
            'grep -n "agy --print" CLAUDE.md',
            '# codex exec later\nls',
        ]
        for cmd in cmds:
            self.assertIsNone(ing.review_tool(cmd), cmd)


class OtherRepoCommits(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(ing, 'HOME', '/Users/me'),
                   mock.patch.object(ing, 'REPO', '/Users/me/code/tattoo-app')]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_commits_into_another_repo_under_code(self):
        cmds = [
            'cd ~/code/ai-usage && git commit -q -m "feat: x"',
            'cd $HOME/code/ai-usage && git add -A && git commit -m x',
            'cd "${HOME}/code/ai-usage"; git commit -m x',
            "cd /Users/me/code/ai-usage\ngit commit -F - <<'EOF'\nfeat: x\nEOF",
            'git -C ~/code/ai-usage commit -m x',
            'cd /Users/me/code/tattoo-app && git -C /Users/me/code/book commit -m x',
            'cd ../ai-usage && git commit -m x',
        ]
        for cmd in cmds:
            self.assertTrue(ing.commits_elsewhere(cmd), cmd)

    def test_commits_in_sable_and_its_worktrees(self):
        cmds = [
            'git commit -m "fix: x"',
            'cd /Users/me/code/tattoo-app && git commit -m x',
            'cd ~/code/tattoo-app/.worktrees/fix-101 && git commit -m x',
            'cd /Users/me/code/tattoo-app/.claude/worktrees/artist-refs; git add x && git commit -m y',
            'git -C /Users/me/code/tattoo-app status && git commit -m x',
            'cd ~/code/ai-usage && python3 ingest.py; cd /Users/me/code/tattoo-app && git commit -m x',
            'cd $S && git commit -m x',
            'git commit -m "docs: cd ~/code/ai-usage first"',
            'cd /private/tmp/scratch && git commit -m x',
            # worktrees kept beside the repo, as `git worktree add ../tattoo-app-radar`
            'cd /Users/me/code/tattoo-app-radar && git add -A && git commit -m x',
            'git -C ~/code/tattoo-app-concepts commit -m x',
        ]
        for cmd in cmds:
            self.assertFalse(ing.commits_elsewhere(cmd), cmd)


class CommitAnchors(unittest.TestCase):
    def test_a_commit_in_another_repo_claims_no_sable_commit(self):
        commits = [{'sha': 'a' * 40, 'short': '2e5c7eb', 'at': t('2026-10-24T10:00:30'),
                    'subject': 'fix(sync): preserve delete ordering across pulls'}]
        cmds = [dict(session='s1', ts=t('2026-10-24T10:00:00'), elsewhere=True)]
        anchors, commit_task = ing.anchor_commits(cmds, commits, set())
        self.assertEqual(commit_task, {})
        # the anchor stays, with no task, so the work before it is not booked to Sable
        self.assertEqual(anchors, [('s1', t('2026-10-24T10:00:00'), None)])
        self.assertIsNone(ing.anchor_task({'s1': [(t('2026-10-24T10:00:00'), None)]}, 's1', t('2026-10-24T09:40:00')))

    def test_a_sable_commit_command_anchors_its_commit(self):
        commits = [{'sha': 'a' * 40, 'short': '2e5c7eb', 'at': t('2026-10-24T10:00:30'), 'subject': 'fix: x (#88)'}]
        cmds = [dict(session='s1', ts=t('2026-10-24T10:00:00'), elsewhere=False)]
        anchors, commit_task = ing.anchor_commits(cmds, commits, {88})
        self.assertEqual(commit_task, {'a' * 40: 'PR #88'})
        self.assertEqual(anchors, [('s1', t('2026-10-24T10:00:30'), 'PR #88')])


class Classify(unittest.TestCase):
    def test_conventional_type(self):
        self.assertEqual(ing.conv_type('feat(home): add pipeline'), 'feat')
        self.assertEqual(ing.conv_type('chore(deps-dev): bump vite'), 'chore')
        self.assertEqual(ing.conv_type('refactor!: drop v1'), 'refactor')
        self.assertEqual(ing.conv_type('Bump vite'), 'other')

    def test_size_bucket(self):
        self.assertEqual([ing.size_bucket(n) for n in (50, 100, 500, 2000, None)], ['S', 'M', 'L', 'XL', None])


class Waveform(unittest.TestCase):
    def test_merges_claude_and_codex_calls_oldest_first_within_the_window(self):
        u = dict(input=1, cw5=10, cw1h=5, cache_read=100, output=7, thinking=0)
        replies = [
            dict(ts=t('2026-10-02T10:00:00'), model='claude-opus-5-5', usage=u, rebuild=True, sidechain=False, task='PR #5'),
            dict(ts=t('2026-08-01T10:00:00'), model='claude-opus-5-5', usage=u, rebuild=False, sidechain=False, task=None),
        ]
        codex = [dict(ts=t('2026-10-01T09:00:00'), model='gpt-6-sol', usage=u, role='review', task=None)]
        w = ing.build_waveform(replies, codex, since=t('2026-09-21T00:00:00'))
        self.assertEqual(w['models'], ['gpt-6-sol', 'claude-opus-5-5'])
        self.assertEqual(w['tasks'], ['PR #5'])
        self.assertEqual(len(w['rows']), 2)  # the August reply is outside the window
        codex_row, claude_row = w['rows']
        # [time, model, tool, context, output, cache write, rebuild, role, task]
        self.assertEqual(codex_row[1:], [0, 1, 116, 7, 15, 0, 2, -1])
        self.assertEqual(claude_row[1:], [1, 0, 116, 7, 15, 1, 0, 0])


class Rework(unittest.TestCase):
    def test_counts_later_fixes_to_the_same_source_files(self):
        shipped = t('2026-10-01T00:00:00')
        main = [
            {'sha': '1', 'at': t('2026-10-03T00:00:00'), 'subject': 'fix(ui): header overlap', 'files': ['src/a.js']},
            {'sha': '2', 'at': t('2026-10-25T00:00:00'), 'subject': 'fix(ui): late fix', 'files': ['src/a.js']},
            {'sha': '3', 'at': t('2026-10-04T00:00:00'), 'subject': 'fix(test): flaky', 'files': ['src/test/a.test.js']},
            {'sha': '4', 'at': t('2026-10-04T00:00:00'), 'subject': 'feat(ui): more', 'files': ['src/a.js']},
            {'sha': '5', 'at': t('2026-10-02T00:00:00'), 'subject': 'fix(ui): own follow-up', 'files': ['src/a.js']},
        ]
        n = ing.rework_count({'src/a.js', 'src/test/a.test.js'}, shipped, main, own={'5'})
        self.assertEqual(n, 1)


def varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7f, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def pb(*fields):
    """Encode (field number, int | str | bytes) pairs as a protobuf message."""
    out = b''
    for num, v in fields:
        if isinstance(v, int):
            out += varint(num << 3) + varint(v)
        else:
            v = v.encode() if isinstance(v, str) else v
            out += varint(num << 3 | 2) + varint(len(v)) + v
    return out


def generation(exec_id='e1', code=1072, name='Gemini 3.6 Flash (Medium)', slug='gemini-3.6-flash',
               request='Design review of Sable, a tattoo PWA'):
    usage = pb((1, code), (2, 1000), (3, 300), (5, 5000), (9, 200), (10, 100))
    chat = [(1, 'You are Antigravity'), (2, pb((2, 1), (3, '<USER_REQUEST>\n' + request + '\n</USER_REQUEST>'))),
            (17, pb((2, usage))), (19, slug)]
    if name:
        chat.append((21, name))
    return pb((3, pb((28, slug))), (4, exec_id), (1, pb(*chat)))


class Protobuf(unittest.TestCase):
    def test_reads_nested_fields(self):
        msg = pb((1, pb((2, 'x'), (3, 7))), (4, 'y'))
        self.assertEqual(ing.pb_get(msg, 1, 3), 7)
        self.assertEqual(ing.pb_get(msg, 1, 2), b'x')
        self.assertEqual(ing.pb_get(msg, 4), b'y')
        self.assertIsNone(ing.pb_get(msg, 1, 9))
        self.assertEqual(ing.pb_all(pb((2, 'a'), (3, 1), (2, 'b')), 2), [b'a', b'b'])

    def test_garbage_reads_as_nothing(self):
        self.assertIsNone(ing.pb_get(b'\xff\xff\xff', 1))
        self.assertIsNone(ing.pb_get(pb((1, 'plain text, not a message')), 1, 5))
        self.assertIsNone(ing.pb_get(None, 1))


class Antigravity(unittest.TestCase):
    def test_reads_a_generation(self):
        g = ing.antigravity_generation(generation())
        self.assertEqual((g['exec'], g['code'], g['name']), ('e1', 1072, 'Gemini 3.6 Flash (Medium)'))
        self.assertEqual(g['request'], 'Design review of Sable, a tattoo PWA')
        # output includes thinking, as it does for Claude and Codex
        self.assertEqual(g['usage'], dict(input=1000, cw5=0, cw1h=0, cache_read=5000, output=300, thinking=200))

    def test_model_ids_drop_the_effort_level(self):
        m = ing.antigravity_model
        self.assertEqual(m('Gemini 3.6 Flash (Medium)'), 'gemini-3.6-flash')
        self.assertEqual(m('Gemini 4 Argon (High)'), 'gemini-4-argon')
        # Claude through Antigravity uses Claude Code's ids, so the two add up
        self.assertEqual(m('Claude Opus 5.5 (High)'), 'claude-opus-5-5')

    def test_unnamed_generations_borrow_the_name_seen_for_their_code(self):
        gens = [ing.antigravity_generation(generation(code=1072)),
                ing.antigravity_generation(generation(code=1072, name=None)),
                ing.antigravity_generation(generation(code=1418, name=None, slug='gemini-4-argon-trial'))]
        self.assertEqual(ing.name_models(gens), ['gemini-3.6-flash', 'gemini-3.6-flash', 'gemini-4-argon-trial'])

    def test_sable_folders(self):
        repo = ing.REPO
        yes = [repo, repo + '/.worktrees/fix-101', 'file://' + repo + '/.claude/worktrees/plan-116',
               '/private/tmp/claude-502/' + repo.replace('/', '-') + '/5a21/scratchpad']
        no = ['/Users/someone/code/other', repo + '-old', '/private/tmp/mistry-review']
        self.assertEqual([ing.is_sable_folder(f) for f in yes], [True] * len(yes))
        self.assertEqual([ing.is_sable_folder(f) for f in no], [False] * len(no))

    def test_a_known_folder_decides_and_otherwise_the_request_must_name_sable(self):
        repo = ing.REPO
        self.assertTrue(ing.antigravity_is_sable(repo, 'Review this diff'))
        self.assertFalse(ing.antigravity_is_sable('/Users/someone/code/book', 'Review the Sable diff'))
        self.assertTrue(ing.antigravity_is_sable(None, 'Design/UX review. Sable is a dark tattoo PWA'))
        self.assertFalse(ing.antigravity_is_sable(None, 'Review only this unified diff for races'))
        other = os.path.join(os.path.dirname(repo), 'book')
        self.assertFalse(ing.antigravity_is_sable(None, 'Compare Sable with ' + other + '/src/a.ts'))

    def test_folders_from_cli_logs_and_history(self):
        log = ['I1021 server.go:323] Creating CLI server backend: product=antigravity workspaceDirs=[/a/sable] appDataDir=x',
               'I1021 server.go:1263] Created conversation 980c2d21-2699-48d3-8481-b1a49779ad2c',
               'I1021 server.go:323] Creating CLI server backend: workspaceDirs=[] appDataDir=x',
               'I1021 server.go:1263] Created conversation 11111111-2222-3333-4444-555555555555']
        hist = ['{"display":"hi","workspace":"/a/sable","conversationId":"933d0182-603b-4966-8794-55ea57d89ea1"}',
                '{"display":"/model","workspace":"/a/sable"}', 'not json']
        folders, interactive = ing.antigravity_cli_folders([log], hist)
        self.assertEqual(folders, {'980c2d21-2699-48d3-8481-b1a49779ad2c': '/a/sable',
                                   '933d0182-603b-4966-8794-55ea57d89ea1': '/a/sable'})
        self.assertEqual(interactive, {'933d0182-603b-4966-8794-55ea57d89ea1'})

    def test_reads_a_conversation_database_without_touching_it(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'c0ffee00-0000-0000-0000-000000000000.db')
            con = sqlite3.connect(path)
            con.executescript('create table trajectory_metadata_blob (id text, data blob);'
                              'create table steps (idx integer, metadata blob);'
                              'create table gen_metadata (idx integer, data blob);')
            con.execute('insert into trajectory_metadata_blob values (?, ?)',
                        ('main', pb((1, pb((1, 'file:///Users/me/My%20Code/sable'))), (2, pb((1, 1790000000))))))
            con.executemany('insert into steps values (?, ?)', [
                (0, pb((1, pb((1, 1790000100))), (12, 'e1'))), (1, pb((1, pb((1, 1790000050))), (12, 'e1'))),
                (2, pb((1, pb((1, 1790090000))), (12, 'e2')))])
            con.executemany('insert into gen_metadata values (?, ?)', [
                (0, generation(exec_id='e1')), (1, generation(exec_id='e2', name=None)), (2, generation(exec_id='e9'))])
            con.commit(), con.close()
            before = os.path.getmtime(path)
            c = ing.read_antigravity_db(path)
            self.assertEqual(os.path.getmtime(path), before)
        self.assertEqual(c['id'], 'c0ffee00-0000-0000-0000-000000000000')
        self.assertEqual(c['folder'], '/Users/me/My Code/sable')
        self.assertEqual(c['request'], 'Design review of Sable, a tattoo PWA')
        # each generation is dated by the first step of its turn, else by the conversation's start
        self.assertEqual([int(g['ts'].timestamp()) for g in c['gens']], [1790000050, 1790090000, 1790000000])


class GeminiCli(unittest.TestCase):
    def test_token_counts(self):
        u = ing.gemini_cli_usage({'input': 19243, 'output': 23, 'cached': 15071, 'thoughts': 151, 'tool': 2})
        # Gemini counts cached tokens inside input and thinking outside output
        self.assertEqual(u, dict(input=4174, cw5=0, cw1h=0, cache_read=15071, output=174, thinking=151))

    def test_each_reply_counts_once(self):
        tokens = {'input': 10, 'output': 1, 'cached': 0, 'thoughts': 0, 'tool': 0}
        records = [
            {'sessionId': 's', 'kind': 'main'},
            {'$set': {'messages': [{'id': 'a', 'type': 'gemini', 'timestamp': '2026-06-04T21:00:00Z',
                                    'model': 'gemini-3-flash-preview', 'tokens': tokens}]}},
            {'id': 'a', 'type': 'gemini', 'timestamp': '2026-06-04T21:00:00Z', 'model': 'gemini-3-flash-preview', 'tokens': tokens},
            {'id': 'b', 'type': 'user', 'timestamp': '2026-06-04T21:01:00Z', 'content': 'hi'},
            {'id': 'c', 'type': 'gemini', 'timestamp': '2026-06-04T21:02:00Z', 'model': 'gemini-3-flash-preview', 'tokens': tokens},
        ]
        replies = ing.gemini_cli_replies(records)
        self.assertEqual([r['model'] for r in replies], ['gemini-3-flash-preview'] * 2)
        self.assertEqual(replies[1]['ts'], t('2026-06-04T21:02:00'))


class Shrink(unittest.TestCase):
    def row(self, day, tool, tokens, model='m'):
        return dict(day=day, tool=tool, model=model, input=tokens, cw5=0, cw1h=0, cache_read=0, output=0, thinking=0)

    def test_growth_and_regrouping_are_fine(self):
        old = [self.row('2026-07-01', 'Codex', 100), self.row('2026-10-21', 'Claude Code', 50)]
        new = [self.row('2026-07-01', 'Codex', 60, model='a'), self.row('2026-07-01', 'Codex', 40, model='b'),
               self.row('2026-10-21', 'Claude Code', 80), self.row('2026-10-26', 'Claude Code', 5)]
        self.assertEqual(ing.shrunk_days(old, new), [])

    def test_reports_days_whose_tokens_went_down_or_vanished(self):
        old = [self.row('2026-07-01', 'Codex', 100), self.row('2026-07-02', 'Codex', 70),
               self.row('2026-07-02', 'Claude Code', 9)]
        new = [self.row('2026-07-01', 'Codex', 99), self.row('2026-07-02', 'Claude Code', 9)]
        self.assertEqual(ing.shrunk_days(old, new),
                         [('2026-07-01', 'Codex', 100, 99), ('2026-07-02', 'Codex', 70, 0)])


if __name__ == '__main__':
    unittest.main()
