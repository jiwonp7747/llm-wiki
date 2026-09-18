# LLM Wiki

원본을 매번 다시 검색하는 대신, LLM이 지속적으로 갱신하는 Markdown 지식베이스를 만들기 위한 plugin입니다. 하나의 저장소로 Codex와 Claude Code 양쪽에 설치됩니다.

두 런타임은 `plugins/llm-wiki/`를 공유하되 서로 다른 manifest를 읽으므로, 한쪽 설치가 다른 쪽에 영향을 주지 않습니다.

| | Codex | Claude Code |
|---|---|---|
| marketplace manifest | `.agents/plugins/marketplace.json` | `.claude-plugin/marketplace.json` |
| plugin manifest | `plugins/llm-wiki/.codex-plugin/plugin.json` | `plugins/llm-wiki/.claude-plugin/plugin.json` |
| hook map | `hooks/hooks.json` (`${PLUGIN_ROOT}`) | `hooks/claude-hooks.json` (`${CLAUDE_PLUGIN_ROOT}`) |

## 구성

- `sources/`: 최초 문서, 사용자 메모, 코드 스냅샷 등 변경하지 않는 근거 자료
- `wiki/`: LLM이 요약·통합·상호연결하는 현재 지식
- `system/`: source 처리 상태, SHA-256, 작업 로그, lint 리포트
- `llm-wiki` skill: init, ingest, query, lint 작업 순서와 승인 경계
- Python scripts: 해시, 등록, 인덱스, 검증, 로그처럼 결과가 결정적인 작업

사용자의 모든 발언을 source로 저장하지 않습니다. 보존 가치가 있는 메모만 출처와 함께 등록하고 `unverified`로 취급합니다. 질문은 `wiki/questions/`에 저장합니다.

## Codex 설치

```bash
codex plugin marketplace add jiwonp7747/llm-wiki
codex plugin add llm-wiki@llm-wiki
```

설치 후 새 Codex task를 시작하고 `/hooks`에서 plugin hook 두 개를 검토하고 신뢰 처리합니다.

## Claude Code 설치

```bash
claude plugin marketplace add jiwonp7747/llm-wiki
claude plugin install llm-wiki@llm-wiki
```

로컬 클론으로 설치할 때는 절대 경로이거나 `./`로 시작하는 경로를 넘깁니다. `.` 하나만 넘기면 거부됩니다. 설치 후 새 세션을 시작하고 `claude plugin details llm-wiki@llm-wiki`로 확인합니다.

## 사용 예시

Codex는 `$llm-wiki`, Claude Code는 `/llm-wiki`로 호출합니다.

```text
$llm-wiki로 이 프로젝트에 지식베이스를 초기화해줘.
$llm-wiki로 이 PDF를 ingest해줘.
$llm-wiki로 현재 아키텍처를 위키 근거와 함께 설명해줘.
$llm-wiki로 위키의 모순과 오래된 내용을 검사해줘.
```

## Hook

- `SessionStart`: 프로젝트에 `knowledge/SCHEMA.md`가 있을 때만 관리 규칙을 세션 컨텍스트에 추가합니다.
- `Stop`: 구조 검증을 실행하고 문제를 알립니다. 파일을 수정하거나 작업을 강제로 계속하지 않습니다.

## 읽기 전용 MCP

`wiki_info`, `wiki_list`, `wiki_search`, `wiki_read`, `wiki_sources`, `wiki_usage`를 제공합니다. 기존 원본 등록·인덱스·검증 스크립트는 유지합니다. `uv`와 Python 3.10 이상이 필요하며 첫 실행 때 잠긴 의존성을 설치합니다. Codex와 Claude Code의 연결 설정은 각 런타임의 플러그인 경로 변수를 사용하고 서버 코드는 공유합니다. 업데이트 설치 후 새 세션에서 도구를 확인합니다.

서버는 `knowledge/` 파일을 수정하지 않습니다. 현재 작업 디렉터리부터 가장 가까운 Git 루트까지 위키를 찾으며, 필요하면 `LLM_WIKI_ROOT` 또는 `--root`로 고정합니다. 초기화 전에는 MCP 서버가 시작되지 않으므로 기존 skill로 위키를 초기화한 뒤 재연결합니다.

검색 결과 노출, 목록 노출, 본문 조회를 구분해 위키 밖의 로컬 SQLite에 자동 기록합니다. 작업별 집계에는 동일한 `task_id`를 전달합니다. 통계는 MCP가 반환을 준비한 결과만 측정하며, 셸 조회나 실제 답변 반영 여부는 측정하지 않습니다.

[도구 계약·페이지 이동·저장 위치·제한·연결 안내](../plugins/llm-wiki/skills/llm-wiki/references/mcp.md)를 참고하세요. 기본 검증은 다음과 같습니다.

```bash
uv sync --frozen --project plugins/llm-wiki
uv run --frozen --project plugins/llm-wiki python -m unittest discover -s tests -v
```
