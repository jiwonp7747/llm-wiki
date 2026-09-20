from __future__ import annotations
import json
import unittest
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
        after = self.service.wiki_usage()
        self.assertEqual(before['calls'], after['calls'])
        self.assertEqual(before['unique_body_read_documents'], after['unique_body_read_documents'])

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
