from __future__ import annotations
import json
import unittest
from contextlib import closing
import test_mcp as fixtures

if fixtures.AVAILABLE:
    from dashboard import create_app
    from starlette.testclient import TestClient


@unittest.skipUnless(fixtures.AVAILABLE, 'Install the locked MCP runtime')
class DashboardTests(unittest.TestCase):
    def setUp(self):
        fixtures.WikiMCPTests.setUp(self)
        self.client = TestClient(create_app(self.service), base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_assets_and_security_headers(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('LLM Wiki', page.text)
        self.assertIn("frame-ancestors 'none'", page.headers['content-security-policy'])
        self.assertEqual(page.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/assets/app.js').status_code, 200)
        self.assertEqual(self.client.post('/api/read').status_code, 405)

    def test_no_dashboard_request_creates_an_mcp_event(self):
        self.service.call('wiki_read', {'path':'wiki/concepts/example.md'})
        self.service.call('wiki_search', {'query':'alpha'})
        before = self.service.wiki_usage()
        for endpoint, args in [('overview',{}), ('pages',{}), ('events',{}),
                               ('read',{'path':'SCHEMA.md'}), ('sources',{'path':'wiki/concepts/example.md'})]:
            response=self.client.get('/api/'+endpoint, params=args)
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('_documents',response.json())
            self.assertNotIn('_metrics',response.json())
        after = self.service.wiki_usage()
        self.assertEqual(before['calls'], after['calls'])
        self.assertEqual(before['unique_body_read_documents'], after['unique_body_read_documents'])

    def record_usage(self, purpose='unknown', origin='unknown', role='unknown', source='unknown',
                     path='wiki/concepts/example.md', **metadata):
        self.service.call('wiki_read', {'path': path, 'task_id': 'shared'})
        fields = {'purpose': purpose, 'execution_origin': origin, 'agent_role': role,
                  'classification_source': source, **metadata}
        with closing(self.service._connect()) as db, db:
            event_id = db.execute('SELECT max(id) FROM events').fetchone()[0]
            db.execute('UPDATE events SET ' + ','.join(f'{key}=?' for key in fields) + ' WHERE id=?',
                       [*fields.values(), event_id])
        return event_id

    def test_purpose_origin_role_and_evidence_filters_agree_for_all_views(self):
        for _ in range(10):
            self.record_usage('maintenance', 'automation', 'subagent', 'inherited')
        self.record_usage('knowledge_lookup', 'automation', 'root', 'explicit')
        self.record_usage('knowledge_lookup', 'interactive', 'subagent', 'explicit')
        self.record_usage('diagnostic', 'interactive', 'root', 'explicit')
        self.record_usage('knowledge_lookup', 'interactive', 'root', 'legacy_inferred')
        self.service.call('wiki_read', {'path': 'wiki/concepts/example.md'})
        scopes = [({'purpose': 'maintenance'}, 10),
                  ({'purpose': 'knowledge_lookup'}, 3),
                  ({'purpose': 'knowledge_lookup', 'execution_origin': 'automation'}, 1),
                  ({'purpose': 'knowledge_lookup', 'agent_role': 'subagent'}, 1),
                  ({'purpose': 'knowledge_lookup', 'classification_source': 'explicit'}, 2),
                  ({'purpose': 'unknown'}, 1), ({'purpose': 'diagnostic'}, 1), ({}, 15)]
        for scope, expected in scopes:
            with self.subTest(scope=scope):
                overview = self.client.get('/api/overview', params=scope).json()
                events = self.client.get('/api/events', params=scope).json()
                pages = self.client.get('/api/pages', params={**scope, 'query': 'example'}).json()
                self.assertEqual(overview['totals']['calls'], expected)
                self.assertEqual(overview['totals']['body_reads'], expected)
                self.assertEqual(events['total'], expected)
                self.assertEqual(pages['items'][0]['reads'], expected)
                self.assertEqual(sum(overview['purpose_counts'].values()), expected)
                self.assertEqual(sum(overview['classification_counts'].values()), expected)
        overview = self.client.get('/api/overview').json()
        self.assertEqual(overview['purpose_counts'], {
            'knowledge_lookup': 3, 'maintenance': 10, 'diagnostic': 1, 'unknown': 1})
        self.assertEqual(overview['classification_counts']['legacy_inferred'], 1)

    def test_event_metadata_and_legacy_unknown_are_preserved(self):
        self.service.call('wiki_read', {'path': 'wiki/concepts/example.md'})
        legacy = self.client.get('/api/events', params={'purpose': 'unknown'}).json()['items'][0]
        self.assertEqual(legacy['classification_source'], 'unknown')
        self.record_usage('knowledge_lookup', 'interactive', 'root', 'explicit',
            duration_ms=1.25, result_count=1, scanned_files=2, scanned_bytes=90,
            client='codex', chat_id='chat', turn_id='turn', tool_use_id='tool-use')
        event = self.client.get('/api/events', params={'purpose': 'knowledge_lookup'}).json()['items'][0]
        self.assertEqual(event['duration_ms'], 1.25)
        self.assertEqual((event['result_count'], event['scanned_files'], event['scanned_bytes']), (1, 2, 90))
        self.assertEqual((event['client'], event['chat_id'], event['turn_id'], event['tool_use_id']),
                         ('codex', 'chat', 'turn', 'tool-use'))

    def test_classification_filter_validation_is_shared(self):
        for endpoint in ('overview', 'events', 'pages'):
            for key in ('purpose', 'execution_origin', 'agent_role', 'classification_source'):
                with self.subTest(endpoint=endpoint, key=key):
                    response = self.client.get('/api/' + endpoint, params={key: "' OR 1=1--"})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()['error'], f'Invalid {key}')

    def test_turn_counts_require_exact_links_and_preserve_mixed_purposes(self):
        identity = {'client': 'codex', 'chat_id': 'chat', 'turn_id': 'mixed'}
        self.record_usage('maintenance', 'automation', 'subagent', 'explicit', **identity)
        for _ in range(2):
            self.record_usage('knowledge_lookup', 'interactive', 'root', 'explicit', **identity)
        self.record_usage('knowledge_lookup', 'interactive', 'root', 'explicit',
                          path='wiki/index.md', client='codex', chat_id='chat', turn_id='index-only')
        self.service.call('wiki_read', {'path': 'wiki/concepts/example.md'})
        with closing(self.service._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS hook_turns (
                    client TEXT, chat_id TEXT, turn_id TEXT, started_at TEXT, ended_at TEXT,
                    status TEXT, purpose TEXT, execution_origin TEXT, agent_role TEXT,
                    classification_source TEXT, parent_chat_id TEXT, parent_turn_id TEXT, agent_id TEXT,
                    PRIMARY KEY(client,chat_id,turn_id));
                CREATE TABLE IF NOT EXISTS hook_citations (
                    client TEXT,chat_id TEXT,turn_id TEXT,path TEXT,
                    PRIMARY KEY(client,chat_id,turn_id,path));
            ''')
            for turn in ('mixed', 'index-only', 'no-call'):
                db.execute('INSERT INTO hook_turns '
                    '(client,chat_id,turn_id,started_at,status,purpose,execution_origin,agent_role,classification_source) '
                    'VALUES(?,?,?,?,?,?,?,?,?)', ('codex', 'chat', turn, '2026-10-21T00:00:00+00:00',
                        'completed', 'unknown', 'unknown', 'unknown', 'unknown'))
            db.executemany('INSERT INTO hook_citations VALUES(?,?,?,?)', [
                ('codex', 'chat', 'mixed', 'wiki/concepts/example.md'),
                ('codex', 'chat', 'index-only', 'wiki/index.md'),
                ('codex', 'chat', 'no-call', 'wiki/concepts/example.md')])
        knowledge = self.client.get('/api/overview', params={'purpose': 'knowledge_lookup'}).json()['turns']
        maintenance = self.client.get('/api/overview', params={'purpose': 'maintenance'}).json()['turns']
        unknown = self.client.get('/api/overview', params={'purpose': 'unknown'}).json()['turns']
        for turns in (knowledge, maintenance):
            self.assertTrue(turns['available'])
            self.assertEqual(turns['canonical_read_turns'], 1)
            self.assertEqual(turns['canonical_read_documents'], 1)
            self.assertEqual(turns['citation_turns'], 1)
            self.assertEqual(turns['hook_only_turns'], 0)
        self.assertEqual(knowledge['observed_turns'], 2)
        self.assertEqual(maintenance['observed_turns'], 1)
        self.assertEqual(unknown['hook_only_turns'], 1)
        self.assertEqual(unknown['observed_turns'], 1)
        self.assertEqual(unknown['canonical_read_turns'], 0)
        self.assertEqual(unknown['unlinked_events'], 1)
        self.assertEqual(unknown['citation_turns'], 1)
        scoped = self.client.get('/api/overview', params={'purpose': 'unknown', 'task_id': 'other'}).json()['turns']
        self.assertEqual(scoped['hook_only_turns'], 0)

    def test_turn_metrics_are_explicit_when_hook_tables_are_absent(self):
        self.record_usage('knowledge_lookup', 'interactive', 'root', 'explicit',
                          client='codex', chat_id='chat', turn_id='turn')
        result = self.client.get('/api/overview', params={'purpose': 'knowledge_lookup'}).json()['turns']
        self.assertFalse(result['available'])
        self.assertEqual(result['canonical_read_turns'], 1)
        self.assertIsNone(result['citation_turns'])
        self.assertIsNone(result['observed_turns'])

    def test_summary_zero_tools_counts_last_call_and_exact_task_filter(self):
        initial=self.client.get('/api/overview').json()
        self.assertEqual(len(initial['tools']),6)
        self.assertEqual(initial['totals']['calls'],0)
        self.service.call('wiki_read', {'path':'wiki/concepts/example.md','task_id':'one'})
        with self.assertRaises(ValueError):
            self.service.call('wiki_read', {'path':'../private','task_id':'two'})
        overview=self.client.get('/api/overview',params={'task_id':'one'}).json()
        read=next(t for t in overview['tools'] if t['name']=='wiki_read')
        self.assertEqual(read['calls'],1)
        self.assertTrue(read['last_call'])
        self.assertIn('inputSchema',read)
        self.assertEqual(overview['totals']['unique_documents'],1)
        self.assertEqual(self.client.get('/api/overview',params={'task_id':"' OR 1=1--"}).json()['totals']['calls'],0)

    def test_catalog_status_search_unread_and_pagination(self):
        self.service.call('wiki_read',{'path':'wiki/concepts/example.md'})
        result=self.client.get('/api/pages',params={'query':'example','page_type':'concept'}).json()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['reads'],1)
        self.assertTrue(result['items'][0]['last_read'])
        unread=self.client.get('/api/pages',params={'query':'example','unread':'true'}).json()
        self.assertEqual(unread['total'],0)
        other_task=self.client.get('/api/pages',params={'query':'example','unread':'true','task_id':'other'}).json()
        self.assertEqual(other_task['total'],1)
        first=self.client.get('/api/pages',params={'limit':1}).json()
        second=self.client.get('/api/pages',params={'limit':1,'offset':1}).json()
        self.assertNotEqual(first['items'][0]['path'],second['items'][0]['path'])

    def test_timeline_errors_ranges_filter_and_paging(self):
        self.service.call('wiki_read',{'path':'wiki/concepts/example.md','start_line':9,'line_count':1})
        with self.assertRaises(ValueError):
            self.service.call('wiki_read',{'path':'../private'})
        result=self.client.get('/api/events',params={'outcome':'failure'}).json()
        self.assertEqual(result['total'],1)
        self.assertIn('wiki-root-relative',result['items'][0]['detail']['error_message'])
        result=self.client.get('/api/events',params={'outcome':'success'}).json()
        self.assertEqual(result['items'][0]['documents'][0]['start_line'],9)
        self.assertEqual(self.client.get('/api/events',params={'limit':1,'offset':1}).json()['items'][0]['success'],1)

    def test_read_continuation_sources_and_hash_conflict(self):
        self.page.write_text('한글\n'*201,encoding='utf-8')
        first=self.client.get('/api/read',params={'path':'wiki/concepts/example.md'}).json()
        self.assertEqual(first['next_cursor']['start_line'],201)
        next_page=self.client.get('/api/read',params={'path':'wiki/concepts/example.md',**first['next_cursor'],'expected_sha256':first['sha256']}).json()
        self.assertEqual(next_page['text'],'한글\n')
        self.page.write_text('changed')
        response=self.client.get('/api/read',params={'path':'wiki/concepts/example.md','expected_sha256':first['sha256']})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.get('/api/sources',params={'source_id':'missing'}).json()['sources'][0]['missing'],True)

    def test_path_symlink_host_origin_and_invalid_filters(self):
        self.assertEqual(self.client.get('/api/read',params={'path':'../private'}).status_code,400)
        (self.root/'wiki/leak.md').symlink_to(self.project/'secret')
        self.assertEqual(self.client.get('/api/read',params={'path':'wiki/leak.md'}).status_code,400)
        self.assertEqual(self.client.get('/api/overview',headers={'host':'evil.example'}).status_code,400)
        self.assertEqual(self.client.get('/api/overview',headers={'origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/overview',headers={'sec-fetch-site':'cross-site'}).status_code,403)
        for args in [{'limit':101},{'offset':-1},{'since':'yesterday'},{'since':'2026-01-01'},
                     {'since':'2026-01-02T00:00:00Z','until':'2026-01-01T00:00:00Z'}]:
            self.assertEqual(self.client.get('/api/events',params=args).status_code,400)
        self.assertEqual(self.client.get('/api/missing').status_code,404)

    def test_wiki_unchanged_by_browsing(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.client.get('/api/read',params={'path':'wiki/index.md'})
        self.client.get('/api/pages')
        after={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

if __name__=='__main__':
    unittest.main()
