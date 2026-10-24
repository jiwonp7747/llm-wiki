from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / 'plugins/llm-wiki'
SCRIPTS = PLUGIN / 'skills/llm-wiki/scripts'
sys.path.insert(0, str(PLUGIN / 'mcp'))
AVAILABLE = importlib.util.find_spec('mcp') is not None and importlib.util.find_spec('regex') is not None
if AVAILABLE:
    from wiki_service import WikiService, discover_root
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client


@unittest.skipUnless(AVAILABLE, 'Install MCP dependencies: uv sync --project plugins/llm-wiki')
class WikiMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.root = self.project / 'knowledge'
        subprocess.run([sys.executable, str(SCRIPTS / 'init_wiki.py'), '--root', str(self.root)],
                       check=True, capture_output=True)
        self.page = self.root / 'wiki/concepts/example.md'
        self.page.write_text('---\nid: example\ntype: concept\nstatus: canonical\nsources: []\ntags: ["runtime"]\n---\n# Example\nAlpha 한글\nalpha beta\nTail\n', encoding='utf-8')
        self.db = self.project / 'audit.sqlite3'
        self.service = WikiService(self.root, self.db, 'test-task')

    def call(self, name, **args):
        return self.service.call(name, args)

    def test_list_filters_paging_and_info(self):
        info = self.call('wiki_info')
        self.assertEqual(info['root'], str(self.root.resolve()))
        self.assertIsNone(info['tag_policy'])
        listed = self.call('wiki_list', page_type='concept', tag='runtime', limit=1)
        self.assertEqual([p['path'] for p in listed['items']], ['wiki/concepts/example.md'])
        self.assertEqual(listed['items'][0]['tags'], ['runtime'])
        self.assertIsNone(listed['next_offset'])
        first = self.call('wiki_list', limit=1)
        second = self.call('wiki_list', limit=1, offset=first['next_offset'])
        self.assertNotEqual(first['items'][0]['path'], second['items'][0]['path'])

    def test_list_tag_filter_is_exact_single_tag_and_combines_with_type(self):
        other = self.root / 'wiki/guides/tagged.md'
        other.write_text('---\nid: tagged\ntype: guide\nstatus: canonical\nsources: []\ntags:\n  - runtime\n  - 활동/운영\n---\n# Tagged\n', encoding='utf-8')
        untagged = self.root / 'wiki/guides/plain.md'
        untagged.write_text('---\nid: plain\ntype: guide\nstatus: canonical\nsources: []\n---\n# Plain\n', encoding='utf-8')
        paths = lambda result: [p['path'] for p in result['items']]
        self.assertEqual(paths(self.call('wiki_list', tag='runtime')), ['wiki/concepts/example.md', 'wiki/guides/tagged.md'])
        self.assertEqual(paths(self.call('wiki_list', tag='활동/운영')), ['wiki/guides/tagged.md'])
        self.assertEqual(paths(self.call('wiki_list', tag='활동')), [])
        self.assertEqual(paths(self.call('wiki_list', tag='Runtime')), [])
        self.assertEqual(paths(self.call('wiki_list', tag='runtime', page_type='guide')), ['wiki/guides/tagged.md'])
        self.assertEqual(paths(self.call('wiki_list', tag='runtime', path_prefix='wiki/guides/')), ['wiki/guides/tagged.md'])
        plain = next(p for p in self.call('wiki_list', path_prefix='wiki/guides/')['items'] if p['path'] == 'wiki/guides/plain.md')
        self.assertEqual(plain['tags'], [])
        (self.root / 'tags.json').write_text('{"tags": {"runtime": "Runtime pages"}}', encoding='utf-8')
        self.assertEqual(self.call('wiki_info')['tag_policy'], 'tags.json')
        self.assertIn('Runtime pages', self.call('wiki_read', path='tags.json')['text'])

    def test_search_literal_regex_context_paging(self):
        first = self.call('wiki_search', query='alpha', limit=1)
        self.assertEqual(first['matches'][0]['line'], 9)
        self.assertEqual(first['next_offset'], 1)
        second = self.call('wiki_search', query='alpha', offset=1, limit=1)
        self.assertEqual(second['matches'][0]['line'], 10)
        self.assertIsNone(second['next_offset'])
        self.assertEqual(len(self.call('wiki_search', query='^alpha', use_regex=True, case_sensitive=True)['matches']), 1)
        self.assertEqual(self.call('wiki_search', query='^alpha')['matches'], [])
        self.assertEqual(len(self.call('wiki_search', query='한글')['matches']), 1)

    def test_search_rejects_source_prefix_instead_of_silent_empty_result(self):
        original = self.root / 'sources' / 'original.md'
        original.write_text('Pasted image', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source originals are not searchable'):
            self.call('wiki_search', query='Pasted image', path_prefix='sources/')
        with self.assertRaisesRegex(ValueError, 'within wiki/'):
            self.call('wiki_list', path_prefix='sources/')
        self.assertEqual(len(self.call('wiki_search', query='Alpha', path_prefix='wiki/concepts/', case_sensitive=True)['matches']), 1)

    def test_read_unicode_long_line_continuation_and_hash(self):
        text = '한글🙂' * 100 + '\nsecond\n'
        self.page.write_text(text, encoding='utf-8')
        cursor, output, expected = {}, '', None
        for _ in range(100):
            result = self.call('wiki_read', path='wiki/concepts/example.md', max_chars=13,
                               expected_sha256=expected, **cursor)
            output += result['text']
            expected = result['sha256']
            cursor = result['next_cursor']
            if cursor is None:
                break
        self.assertEqual(output, text)
        self.assertEqual(expected, hashlib.sha256(text.encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'Unsupported cursor argument'):
            self.call('wiki_read', path='wiki/concepts/example.md', cursor={'start_line': 2, 'start_column': 0})
        self.page.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.call('wiki_read', path='wiki/concepts/example.md', expected_sha256=expected)

    def test_read_range_empty_and_eof(self):
        result = self.call('wiki_read', path='wiki/concepts/example.md', start_line=9, line_count=1)
        self.assertEqual(result['text'], 'Alpha 한글\n')
        self.assertEqual(result['next_cursor'], {'start_line': 10, 'start_column': 0})
        self.page.write_text('', encoding='utf-8')
        self.assertEqual(self.call('wiki_read', path='wiki/concepts/example.md')['text'], '')
        with self.assertRaises(ValueError):
            self.call('wiki_read', path='wiki/concepts/example.md', start_line=3)

    def test_query_client_follows_cursor_once_per_range(self):
        content = ''.join(f'Line {n}\n' for n in range(451))
        self.page.write_text(content, encoding='utf-8')
        call = {'name': 'wiki_read', 'arguments': {'path': 'wiki/concepts/example.md'}}
        process = subprocess.run([sys.executable, str(REPO / 'examples/mcp_query.py'),
            '--root', str(self.root), '--audit-db', str(self.db), '--task-id', 'follow-test',
            '--follow-cursor'], input=json.dumps(call), capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)['result']
        self.assertEqual(result['text'], content)
        self.assertEqual(result['read_calls'], 3)
        self.assertEqual(len(result['audit_event_ids']), 3)
        self.assertIsNone(result['next_cursor'])
        usage = self.call('wiki_usage', filter_task_id='follow-test')
        self.assertEqual(usage['documents'][0]['body_reads'], 3)

    def test_block_escape_absolute_symlink_and_system_logs(self):
        secret = self.project / 'secret.txt'
        secret.write_text('secret')
        link = self.root / 'wiki/leak.md'
        link.symlink_to(secret)
        inside = self.root / 'wiki/alias.md'
        inside.symlink_to(self.page)
        for path in ['../secret.txt', str(secret), 'wiki/leak.md', 'wiki/alias.md', 'system/log.md']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.call('wiki_read', path=path)
        self.assertFalse(self.call('wiki_search', query='secret')['matches'])
        self.assertNotIn('wiki/leak.md', [p['path'] for p in self.call('wiki_list')['items']])
        (self.root / 'wiki/outside').symlink_to(self.project, target_is_directory=True)
        self.assertFalse(self.call('wiki_search', query='secret')['matches'])

    def test_binary_large_files_and_skips(self):
        self.page.write_bytes(b'%PDF\x00binary')
        with self.assertRaisesRegex(ValueError, 'Binary'):
            self.call('wiki_read', path='wiki/concepts/example.md')
        self.assertEqual(self.call('wiki_search', query='binary')['skipped_count'], 1)
        self.page.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            self.call('wiki_read', path='wiki/concepts/example.md')

    def test_regex_timeout_and_invalid_pattern(self):
        self.page.write_text('a' * 50000 + '!')
        with self.assertRaisesRegex(ValueError, 'timed out'):
            self.call('wiki_search', query='(a+)+$', use_regex=True)
        with self.assertRaises(Exception):
            self.call('wiki_search', query='[', use_regex=True)

    def test_source_resolution_and_read_original(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'intake_source.py'), '--text', 'Source evidence', '--kind', 'user-note',
                                 '--root', str(self.root)], capture_output=True, text=True, check=True)
        source_id = json.loads(result.stdout)['source_id']
        source = self.call('wiki_sources', source_id=source_id)['sources'][0]
        self.assertTrue(source['accessible'])
        self.assertEqual(source['verification'], 'unverified')
        self.assertEqual(self.call('wiki_read', path=source['stored_path'])['text'], 'Source evidence')
        page = 'wiki/source-notes/' + source_id + '.md'
        self.assertEqual(self.call('wiki_sources', path=page)['sources'][0]['source_id'], source_id)
        self.assertTrue(self.call('wiki_sources', source_id='missing')['sources'][0]['missing'])
        with self.assertRaises(ValueError):
            self.call('wiki_sources', path=page, source_id=source_id)

    def test_usage_distinguishes_exposure_and_reads(self):
        self.call('wiki_search', query='alpha')
        self.call('wiki_list')
        self.call('wiki_read', path='wiki/concepts/example.md')
        self.call('wiki_read', path='wiki/concepts/example.md')
        with self.assertRaises(ValueError):
            self.call('wiki_read', path='../secret')
        usage = self.call('wiki_usage', filter_task_id='test-task')
        doc = next(d for d in usage['documents'] if d['path'] == 'wiki/concepts/example.md')
        self.assertEqual(doc['body_reads'], 2)
        self.assertEqual(doc['search_exposures'], 1)
        self.assertEqual(doc['list_exposures'], 1)
        self.assertEqual(usage['unique_body_read_documents'], 1)
        self.assertIn({'tool': 'wiki_read', 'success': 0, 'calls': 1}, usage['calls'])
        self.assertEqual(self.call('wiki_usage', filter_task_id='other')['documents'], [])
        self.assertEqual(self.call('wiki_usage', since='2999-01-01T00:00:00Z')['documents'], [])
        with self.assertRaises(ValueError):
            self.call('wiki_usage', since='2026-01-01')
        raw = sqlite3.connect(self.db).execute('SELECT detail FROM events').fetchall()
        self.assertNotIn('Alpha 한글', str(raw))

    def test_concurrent_services_preserve_events(self):
        services = [WikiService(self.root, self.db, 'parallel') for _ in range(4)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda n: services[n % 4].call('wiki_read', {'path': 'wiki/concepts/example.md'}), range(40)))
        self.assertEqual(len({r['audit']['event_id'] for r in results}), 40)
        usage = self.call('wiki_usage', filter_task_id='parallel')
        self.assertEqual(usage['documents'][0]['body_reads'], 40)

    def test_wiki_files_unchanged_and_audit_separate(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.call('wiki_info')
        self.call('wiki_search', query='alpha')
        self.call('wiki_read', path='SCHEMA.md')
        self.call('wiki_usage')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        with self.assertRaises(ValueError):
            WikiService(self.root, self.root / 'audit.sqlite3')
        other = self.project / 'other'
        other.mkdir()
        (other / 'SCHEMA.md').write_text('schema')
        with self.assertRaisesRegex(ValueError, 'another wiki'):
            WikiService(other, self.db)

    def test_discovery_obeys_git_boundary(self):
        nested = self.project / 'src/nested'
        nested.mkdir(parents=True)
        self.assertEqual(discover_root(nested), self.root.resolve())
        (nested / '.git').write_text('gitdir: /tmp/example')
        with self.assertRaises(ValueError):
            discover_root(nested)

    def test_response_limit_and_audit_failure_do_not_report_success(self):
        with patch.object(self.service, 'wiki_info', return_value={'large': 'x' * 64001}):
            with self.assertRaisesRegex(ValueError, '64000'):
                self.call('wiki_info')
        with patch.object(self.service, '_record', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.call('wiki_read', path='SCHEMA.md')
        usage = self.call('wiki_usage')
        self.assertEqual(usage['unique_body_read_documents'], 0)
        self.assertIn({'tool': 'wiki_info', 'success': 0, 'calls': 1}, usage['calls'])

    def test_plugin_launch_config_and_environment_root(self):
        codex = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())['mcpServers']['llm-wiki']
        claude = json.loads((PLUGIN / '.mcp.json').read_text())['mcpServers']['llm-wiki']
        self.assertEqual(codex['command'], 'uv')
        self.assertEqual([value.replace('${PLUGIN_ROOT}', '${CLAUDE_PLUGIN_ROOT}') for value in codex['args']], claude['args'])
        self.assertIn('--frozen', codex['args'])
        server = subprocess.run([sys.executable, str(PLUGIN / 'mcp/server.py')], input='',
                                capture_output=True, text=True, timeout=10,
                                env={**os.environ, 'LLM_WIKI_ROOT': str(self.root), 'LLM_WIKI_AUDIT_DB': str(self.db)})
        self.assertEqual(server.returncode, 0, server.stderr)

    @unittest.skipUnless(shutil.which('uv'), 'uv is required for plugin startup')
    def test_actual_plugin_uv_startup_preserves_project_cwd(self):
        async def exercise():
            config = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())['mcpServers']['llm-wiki']
            args = [arg.replace('${PLUGIN_ROOT}', str(PLUGIN)) for arg in config['args']]
            parameters = StdioServerParameters(command=shutil.which('uv'), args=args,
                cwd=str(self.project), env={'LLM_WIKI_AUDIT_DB': str(self.db)})
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool('wiki_info', {})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent['root'], str(self.root.resolve()))
        asyncio.run(exercise())

    def test_server_stays_connected_without_project_wiki(self):
        async def exercise():
            empty = self.project / 'no-wiki'
            empty.mkdir()
            (empty / '.git').mkdir()
            env = {key: value for key, value in os.environ.items() if key != 'LLM_WIKI_ROOT'}
            parameters = StdioServerParameters(command=sys.executable, args=[str(PLUGIN / 'mcp/server.py')],
                                               cwd=str(empty), env=env)
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool('wiki_info', {})
                    self.assertTrue(result.isError)
                    self.assertIn('No initialized knowledge/', result.content[0].text)
        asyncio.run(exercise())

    def test_registered_wikis_are_listed_and_selected_by_name(self):
        other = Path(self.temp.name) / 'other/knowledge'
        subprocess.run([sys.executable, str(SCRIPTS / 'init_wiki.py'), '--root', str(other)],
                       check=True, capture_output=True)
        (other / 'wiki/concepts/only-other.md').write_text(
            '---\nid: only-other\ntype: concept\nstatus: canonical\nsources: []\n---\n# Other\nzeta marker\n',
            encoding='utf-8')
        registry = Path(self.temp.name) / 'wikis.json'
        registry.write_text(json.dumps({'wikis': [
            {'name': 'main', 'root': str(self.root), 'description': 'test main'},
            {'name': 'other', 'root': str(other), 'description': 'test other'}]}), encoding='utf-8')
        empty = self.project / 'no-wiki'
        empty.mkdir()
        (empty / '.git').mkdir()
        env = {key: value for key, value in os.environ.items() if key != 'LLM_WIKI_ROOT'}
        env.update({'LLM_WIKI_REGISTRY': str(registry), 'XDG_STATE_HOME': str(self.project / 'state')})

        async def exercise(cwd):
            parameters = StdioServerParameters(command=sys.executable, args=[str(PLUGIN / 'mcp/server.py')],
                                               cwd=str(cwd), env=env)
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    init = await client.initialize()
                    catalog = (await client.call_tool('wiki_catalog', {})).structuredContent
                    info = await client.call_tool('wiki_info', {})
                    other_info = await client.call_tool('wiki_info', {'wiki': 'other'})
                    hit = await client.call_tool('wiki_search', {'query': 'zeta marker', 'wiki': 'other'})
                    raw_path = await client.call_tool('wiki_info', {'wiki': '../other/knowledge'})
                    return init.instructions, catalog, info, other_info, hit, raw_path

        instructions, catalog, info, other_info, hit, raw_path = asyncio.run(exercise(empty))
        self.assertIn('wiki/overview.md', instructions)
        self.assertNotIn('wiki_read for SCHEMA.md and wiki/index.md', instructions)
        self.assertEqual([(w['name'], w['default']) for w in catalog['wikis']], [('main', False), ('other', False)])
        self.assertTrue(info.isError)
        self.assertIn('main, other', info.content[0].text)
        self.assertFalse(other_info.isError)
        self.assertEqual(other_info.structuredContent['root'], str(other.resolve()))
        self.assertEqual(other_info.structuredContent['overview'], 'wiki/overview.md')
        self.assertEqual(hit.structuredContent['matches'][0]['path'], 'wiki/concepts/only-other.md')
        self.assertTrue(raw_path.isError)
        self.assertIn('Unknown wiki', raw_path.content[0].text)

        _, catalog, info, _, _, _ = asyncio.run(exercise(self.project))
        self.assertEqual([(w['name'], w['default']) for w in catalog['wikis']], [('main', True), ('other', False)])
        self.assertEqual(info.structuredContent['root'], str(self.root.resolve()))

    def test_registry_rejects_relative_roots_and_duplicate_names(self):
        from wiki_service import load_registry
        registry = Path(self.temp.name) / 'bad.json'
        for wikis in ([{'name': 'a', 'root': 'relative/knowledge'}],
                      [{'name': 'a', 'root': str(self.root)}, {'name': 'a', 'root': str(self.root)}],
                      [{'name': 'Bad Name', 'root': str(self.root)}]):
            registry.write_text(json.dumps({'wikis': wikis}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_registry(registry)
        self.assertEqual(load_registry(Path(self.temp.name) / 'missing.json'), [])

    def test_real_stdio_mcp_schema_errors_and_calls(self):
        async def exercise():
            parameters = StdioServerParameters(command=sys.executable, args=[str(PLUGIN / 'mcp/server.py'),
                '--root', str(self.root), '--audit-db', str(self.db), '--task-id', 'stdio'])
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = (await client.list_tools()).tools
                    self.assertEqual({t.name for t in tools}, {'wiki_catalog','wiki_info','wiki_list','wiki_search','wiki_read','wiki_sources','wiki_usage'})
                    for tool in tools:
                        self.assertTrue(tool.annotations.readOnlyHint)
                    for name, args in [('wiki_info', {}), ('wiki_list', {}), ('wiki_search', {'query':'alpha'}),
                                       ('wiki_read', {'path':'wiki/concepts/example.md'}),
                                       ('wiki_sources', {'path':'wiki/concepts/example.md'}), ('wiki_usage', {'filter_task_id':'stdio'})]:
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, result)
                        self.assertIn('audit', result.structuredContent)
                    invalid = await client.call_tool('wiki_read', {'path':'SCHEMA.md', 'start_line':0})
                    self.assertTrue(invalid.isError)
                    ignored_cursor = await client.call_tool('wiki_read', {'path':'wiki/concepts/example.md',
                        'cursor': {'start_line': 2, 'start_column': 0}})
                    self.assertTrue(ignored_cursor.isError)
                    traversal = await client.call_tool('wiki_read', {'path':'../secret'})
                    self.assertTrue(traversal.isError)
                    still_alive = await client.call_tool('wiki_info', {})
                    self.assertFalse(still_alive.isError)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
