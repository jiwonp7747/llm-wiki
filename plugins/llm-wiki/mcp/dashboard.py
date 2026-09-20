#!/usr/bin/env python3
"""Serve the read-only LLM Wiki dashboard over loopback HTTP, independently of MCP."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from server import create_server
from wiki_service import WikiService, discover_root, MAX_SCAN_BYTES
from wiki_common import parse_frontmatter, page_title

ASSETS = Path(__file__).resolve().parents[1] / 'dashboard/dist'


def filters(query):
    clauses, values = [], []
    for field in ('task_id', 'tool', 'session_id'):
        if query.get(field):
            if len(query[field]) > 200:
                raise ValueError('Filter must be at most 200 characters')
            clauses.append(f'e.{field}=?')
            values.append(query[field])
    if query.get('outcome'):
        if query['outcome'] not in ('success', 'failure'):
            raise ValueError('Invalid outcome')
        clauses.append('e.success=?')
        values.append(int(query['outcome'] == 'success'))
    dates = {}
    for key, operator in (('since', '>='), ('until', '<')):
        if query.get(key):
            value = datetime.fromisoformat(query[key].replace('Z', '+00:00'))
            if value.tzinfo is None:
                raise ValueError('Time filters require an ISO-8601 timezone')
            dates[key] = value
            clauses.append(f'e.time {operator} ?')
            values.append(value.astimezone(timezone.utc).isoformat())
    if len(dates) == 2 and dates['since'] >= dates['until']:
        raise ValueError('since must be earlier than until')
    return ' WHERE ' + (' AND '.join(clauses) if clauses else '1=1'), values


def pagination(query):
    offset, limit = int(query.get('offset', 0)), int(query.get('limit', 25))
    WikiService._pagination(offset, limit)
    return offset, limit


def document_stats(db, where, values):
    rows = db.execute('''SELECT d.path,
        COUNT(DISTINCT CASE WHEN d.kind='body_read' THEN e.id END) AS reads,
        MAX(CASE WHEN d.kind='body_read' THEN e.time END) AS last_read,
        COUNT(DISTINCT CASE WHEN d.kind='search_hit' THEN e.id END) AS searches,
        COUNT(DISTINCT CASE WHEN d.kind IN ('source_metadata','source_reference') THEN e.id END) AS source_lookups
        FROM documents d JOIN events e ON e.id=d.event_id''' + where + ' GROUP BY d.path', values)
    return {r['path']: dict(r) for r in rows}


def create_app(service: WikiService):
    @asynccontextmanager
    async def lifespan(app):
        app.state.tools = [t.model_dump() for t in await create_server(service).list_tools()]
        yield

    def api(request):
        q, endpoint = request.query_params, request.path_params['endpoint']
        try:
            if endpoint == 'read':
                result = service.wiki_read(q.get('path', ''), start_line=int(q.get('start_line', 1)),
                    start_column=int(q.get('start_column', 0)), line_count=200, max_chars=24000,
                    expected_sha256=q.get('expected_sha256'))
                result.pop('_documents', None)
                return JSONResponse(result)
            if endpoint == 'sources':
                offset, limit = pagination(q)
                result = service.wiki_sources(path=q.get('path'), source_id=q.get('source_id'), offset=offset, limit=limit)
                result.pop('_documents', None)
                return JSONResponse(result)
            if endpoint not in ('overview', 'events', 'pages'):
                return JSONResponse({'error': 'Unknown endpoint'}, status_code=404)
            where, values = filters(q)
            with closing(service._connect()) as db:
                db.execute('BEGIN')
                if endpoint == 'overview':
                    rows = {r['tool']: dict(r) for r in db.execute(
                        'SELECT tool, count(*) AS calls, sum(success) AS successes, sum(1-success) AS failures, '
                        'max(time) AS last_call FROM events e' + where + ' GROUP BY tool', values)}
                    tools = [{**t, **rows.get(t['name'], {'calls': 0, 'successes': 0, 'failures': 0, 'last_call': None})}
                             for t in request.app.state.tools]
                    tasks = [r[0] for r in db.execute('SELECT DISTINCT task_id FROM events WHERE task_id IS NOT NULL ORDER BY task_id LIMIT 500')]
                    stats = document_stats(db, where, values)
                    return JSONResponse({'tools': tools, 'tasks': tasks, 'info': service.wiki_info(),
                        'totals': {'calls': sum(t['calls'] for t in tools), 'failures': sum(t['failures'] for t in tools),
                                   'body_reads': sum(d['reads'] for d in stats.values()),
                                   'unique_documents': sum(d['reads'] > 0 for d in stats.values())}})
                if endpoint == 'events':
                    offset, limit = pagination(q)
                    total = db.execute('SELECT count(*) FROM events e' + where, values).fetchone()[0]
                    items = []
                    for row in db.execute('SELECT e.* FROM events e' + where + ' ORDER BY e.id DESC LIMIT ? OFFSET ?', [*values, limit, offset]):
                        event = dict(row)
                        event['detail'] = json.loads(event['detail'])
                        event['documents'] = [dict(r) for r in db.execute('SELECT * FROM documents WHERE event_id=? LIMIT 100', (event['id'],))]
                        event['document_count'] = db.execute('SELECT count(*) FROM documents WHERE event_id=?', (event['id'],)).fetchone()[0]
                        items.append(event)
                    return JSONResponse({'items': items, 'total': total, 'offset': offset, 'limit': limit})
                stats = document_stats(db, where, values)
            offset, limit = pagination(q)
            items, skipped, size = [], [], 0
            for path in service._pages('wiki/'):
                try:
                    text, digest, count = service._text(path)
                except (ValueError, OSError):
                    skipped.append(path)
                    continue
                size += count
                if size > MAX_SCAN_BYTES:
                    raise ValueError('Catalog exceeds 32 MiB')
                meta, body = parse_frontmatter(text)
                title = page_title(body, Path(path).stem)
                if q.get('status', 'canonical') and meta.get('status') != q.get('status', 'canonical'):
                    continue
                if q.get('page_type') and meta.get('type') != q['page_type']:
                    continue
                if q.get('query', '').casefold() not in (title + ' ' + path).casefold():
                    continue
                usage = stats.get(path, {'reads': 0, 'last_read': None, 'searches': 0, 'source_lookups': 0})
                if q.get('unread') == 'true' and usage['reads']:
                    continue
                sources = meta.get('sources', [])
                items.append({'path': path, 'title': title[:200], 'type': str(meta.get('type', ''))[:40],
                              'status': str(meta.get('status', ''))[:40], 'updated': str(meta.get('updated', ''))[:40],
                              'source_count': len(sources) if isinstance(sources, list) else 0,
                              'sha256': digest, **usage})
            return JSONResponse({'items': items[offset:offset + limit], 'total': len(items), 'offset': offset,
                                 'limit': limit, 'skipped': skipped[:20], 'skipped_count': len(skipped)})
        except (ValueError, TypeError) as exc:
            return JSONResponse({'error': str(exc)[:300]}, status_code=400)
        except OSError:
            return JSONResponse({'error': 'File is unavailable or cannot be read'}, status_code=404)
        except sqlite3.Error:
            return JSONResponse({'error': 'Audit database is unavailable'}, status_code=503)

    app = Starlette(routes=[Route('/', lambda r: FileResponse(ASSETS / 'index.html')),
                            Route('/api/{endpoint}', api), Mount('/assets', StaticFiles(directory=ASSETS))],
                    middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])],
                    lifespan=lifespan)

    async def local_only(request, call_next):
        origin = request.headers.get('origin')
        if (request.headers.get('sec-fetch-site') == 'cross-site' or
                (origin and (urlsplit(origin).netloc != request.headers.get('host') or urlsplit(origin).scheme != 'http'))):
            return JSONResponse({'error': 'Cross-origin requests are not allowed'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=local_only)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.environ.get('LLM_WIKI_ROOT'))
    parser.add_argument('--audit-db', default=os.environ.get('LLM_WIKI_AUDIT_DB'))
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    if not (ASSETS / 'index.html').is_file():
        parser.error('Dashboard assets missing; run npm ci && npm run build in dashboard/')
    service = WikiService(Path(args.root) if args.root else discover_root(Path.cwd()),
                          Path(args.audit_db) if args.audit_db else None)
    uvicorn.run(create_app(service), host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
