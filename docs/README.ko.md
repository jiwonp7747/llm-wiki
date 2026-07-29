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

## MCP를 포함하지 않은 이유

초기 버전은 로컬 파일과 Git이 중심이므로 skill 내부 Python script로 충분합니다. 실제 사용 후 여러 클라이언트에서 동일한 타입 도구가 필요하거나 원격 저장소 연동이 필요해질 때 MCP를 추가하는 편이 단순하고 안전합니다.
