# LLM Wiki 사용 기록 대시보드

LLM Wiki 플러그인의 읽기 전용 HTTP 화면이다. Blueprint.js/React 정적 자산과
Starlette API를 같은 로컬 서버에서 제공한다. MCP stdio 서버와 독립 프로세스로
실행하지만 같은 WikiService와 SQLite 사용 기록을 읽는다. MCP 도구는 추가하지 않는다.

## 실행

저장소 루트에서 실행한다.

```bash
uv sync --frozen --project plugins/llm-wiki
uv run --frozen --project plugins/llm-wiki python plugins/llm-wiki/mcp/dashboard.py --root /absolute/path/to/knowledge
```

브라우저에서 `http://127.0.0.1:8766`을 연다. 종료는 실행 터미널에서 Ctrl+C.
포트 변경은 `--port`, 별도 감사 DB는 `--audit-db /absolute/path/access.sqlite3`를 사용한다.
`LLM_WIKI_ROOT`와 `LLM_WIKI_AUDIT_DB`도 지원한다. MCP에서 별도 DB를 지정했다면
대시보드도 같은 DB를 지정해야 한다. DB 기본 위치는 기존 MCP의 root별 경로를 따른다.
설치된 플러그인에서는 위 명령의 project와 script 경로를 해당 플러그인 경로로 바꾼다.

## 화면과 집계 기준

- 도구 사용 현황: 6개 도구 전체, 설명과 실제 입력 스키마, 호출·성공·실패 횟수와 마지막 호출.
- 기간과 작업: 전체·오늘·최근 7/30일·직접 지정, 정확한 task_id 필터, 선택적 30초 자동 갱신.
- 인덱스: Markdown/원문, 내부 문서 링크, 긴 인덱스 이어 읽기.
- 정본과 문서: 기본 canonical, 제목·경로 검색, 상태·종류·미조회 필터, 갱신일·출처 수·조회 수·마지막 조회.
- 문서 상세: 행 더블클릭 또는 제목 버튼, 본문/원문 전환, 경로 복사, 이전 문서, 출처별 상태와 원본 열기.
- 호출 타임라인: 최신순, 도구·성공/실패 필터, 서버 세션, 반환 경로·행 범위·해시·잘림과 오류 정보.

본문 조회는 `body_read` 기록을 가진 호출과 경로의 조합이다. 고유 조회 문서는 경로를
중복 제거한다. 검색 노출은 본문 조회와 별도로 표시한다. 미조회는 선택한 기간·작업의
본문 조회가 0인 문서다. 현재 파일과 과거 기록은 다를 수 있어 기록의 해시를 함께 표시한다.
시간은 브라우저 현지 시간으로 표시하고 API 기간은 시간대가 있는 ISO-8601을 사용한다.
시작은 포함, 종료는 미포함이다. 최근 7/30일은 해당 일수 전 현지 자정부터다.

웹 조회는 사용 기록을 남기지 않는다. 기존 감사 기록은 MCP 서비스가 응답을 준비했다는
증거이며 셸 읽기, 모델이 실제 이해했는지 또는 답변에 활용했는지까지 증명하지 않는다.
이전 실패 기록에 오류 메시지가 없다면 오류 종류만 표시한다.

## HTTP API

모든 API는 GET이며 JSON을 반환한다.

| 경로 | 내용 |
| --- | --- |
| `/api/overview` | 도구 정의, 집계, task_id 목록, 위키 정보 |
| `/api/events` | 호출 목록과 오류·문서 정보 |
| `/api/pages` | 현재 문서 목록과 사용 통계 |
| `/api/read?path=wiki/index.md` | 현재 본문, 해시, 이어 읽기 커서 |
| `/api/sources?path=wiki/concepts/example.md` | 연결된 출처와 원본 경로 |

집계 API는 `task_id`, `since`, `until`, `tool`, `session_id`, `outcome` 필터를 지원한다.
목록은 `offset`(0부터)과 `limit`(기본 25, 최대 100)을 받는다.
문서 목록은 추가로 `query`, `status`(기본 canonical), `page_type`, `unread=true`를 받는다.
본문은 요청당 최대 200행·24,000 Unicode 문자이며, 반환된 `next_cursor`의
`start_line`(1부터), `start_column`(0부터)을 사용한다. `expected_sha256`을 함께 보내면
이어 읽는 동안 파일이 바뀐 경우 오류를 반환한다. 출처 목록은 기본 25개, 화면에서는 10개씩이다.

127.0.0.1에서만 수신하며 외부 Host/Origin, 루트 밖 경로, 심볼릭 링크를 차단한다.
Markdown의 HTML을 실행하지 않고 외부 이미지를 로딩하지 않는다.
서비스 공개·원격 접근용 인증 기능은 포함하지 않는다.

## 프런트엔드 수정

```bash
npm ci --prefix plugins/llm-wiki/dashboard
npm run build --prefix plugins/llm-wiki/dashboard
```

소스와 `dist/`를 함께 커밋한다. 실행 시 Node.js나 CDN 연결이 필요하지 않는다.
CI는 잠금 파일로 재빌드한 자산이 커밋된 자산과 같은지 확인한다.
Blueprint.js 화면과 안전한 Markdown 렌더링을 위해 npm 의존성을 사용하며,
HTTP 서버는 기존 MCP 의존성에 포함된 Starlette/uvicorn을 명시적으로 선언했다.

## 검증

`tests/test_dashboard.py`는 집계·필터·페이지 이동·본문 커서/해시·출처·경로 제한,
Host/Origin 제한, 읽기 전용 동작, 대시보드 조회의 통계 비반영을 검증한다.
전체 실행은 저장소 AGENTS.md의 검증 명령을 따른다.
브라우저에서는 실제 위키의 정본 더블클릭, 이어 읽기와 원본 열기를 확인했고,
별도 임시 위키에서 실패 타임라인과 Markdown 비실행을 확인했다.
로컬 전체 테스트 28개, skill/plugin 검증, 프런트엔드 빌드가 통과했다.
390px 모바일 화면에서 가로 넘침이 없었고 브라우저 콘솔 오류가 없었다.
