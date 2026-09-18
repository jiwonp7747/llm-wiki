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
        listed = self.call('wiki_list', page_type='concept', tag='runtime', limit=1)
        self.assertEqual([p['path'] for p in listed['items']], ['wiki/concepts/example.md'])
        self.assertIsNone(listed['next_offset'])
        first = self.call('wiki_list', limit=1)
        second = self.call('wiki_list', limit=1, offset=first['next_offset'])
        self.assertNotEqual(first['items'][0]['path'], second['items'][0]['path'])

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

    def test_real_stdio_mcp_schema_errors_and_calls(self):
        async def exercise():
            parameters = StdioServerParameters(command=sys.executable, args=[str(PLUGIN / 'mcp/server.py'),
                '--root', str(self.root), '--audit-db', str(self.db), '--task-id', 'stdio'])
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = (await client.list_tools()).tools
                    self.assertEqual({t.name for t in tools}, {'wiki_info','wiki_list','wiki_search','wiki_read','wiki_sources','wiki_usage'})
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
                    traversal = await client.call_tool('wiki_read', {'path':'../secret'})
                    self.assertTrue(traversal.isError)
                    still_alive = await client.call_tool('wiki_info', {})
                    self.assertFalse(still_alive.isError)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
