"""Unit tests for the pure parts of ingest.py: run with `python3 -m unittest -v`."""
import unittest
from datetime import datetime, timezone

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


if __name__ == '__main__':
    unittest.main()
