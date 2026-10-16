# Hermes_Plugin_00.Jev

이 플러그인은 작업마다 TypeSafe **Jev**가 **사용자가 허용한 모델** 중 하나를 직접 고르게 하고, 그 모델로 작업을 실행합니다. Jev에게는 모델마다 **Artificial Analysis 벤치마크 점수**와 **구독 잔량**을 함께 보냅니다. 실행은 Hermes의 하위 에이전트(subagent)로 하며, 이 하위 에이전트는 현재 세션에 연결됩니다. 원본 작업 세션은 `20261015_181657_b4fee8`과 이 플러그인을 만든 세션입니다.

- **`jev_router_models`**
  - `widget`: 허용할 모델을 체크하는 화면을 띄웁니다.
  - `options`: 허용 모델마다 AA 점수, 가격, 구독 잔량을 한 줄로 정리해 Jev `choice`에 넘길 선택지를 만듭니다.
  - `available` / `show` / `save`: 이 Hermes에서 인증된 모델 조회, 허용 목록 조회와 저장입니다. 그래서 PC나 구독이 달라도 그 환경의 모델로 다시 고르면 됩니다.
- **`jev_delegate`**: Jev가 고른 모델(`provider/model`)이 허용 목록에 있는지 확인한 뒤, 그 모델로 하위 에이전트를 실행합니다(공개 플러그인 API `ctx.subagent_lifecycle`). `tasks=[...]`로 여러 작업을 한 번에 넘기면 병렬로 실행하고 `results[]`를 같은 순서로 돌려줍니다(0.4.0).
- **`pre_tool_call` hook (0.4.0)**: 허용 모델이 저장돼 있으면 `delegate_task`의 하위 에이전트 생성(spawn)을 막고, Jev 라우팅 절차(`options` → Jev `choice`/`classify` → `jev_delegate`)를 안내 메시지로 돌려줍니다. 다른 Skill이 `delegate_task`를 지시해도 Jev를 거치게 하려는 장치입니다. 허용 모델이 없으면 개입하지 않고, `delegate_task`의 list/steer/stop은 그대로 통과합니다.
- **Skill `jev-router:jev-model-router`**: 처음 설정하는 방법, Jev 질문 방식, 작업 중 질문 처리 절차를 담고 있습니다. 하위 에이전트에 위임할 때도 로드되도록 설명을 "Use when delegating subagents or choosing a model per task"로 두었습니다.

### 두 가지 제약을 이렇게 해결합니다
| 제약 | 해결 방법 |
|---|---|
| 작업마다 모델을 바꿀 수 없음 | `subagent_lifecycle.launch(provider, model)`로 실행할 때마다 모델을 지정합니다. 전역 config는 바꾸지 않습니다. |
| 세션 기록이 따로 남음 | 하위 에이전트가 같은 세션 DB에 `parent_session_id`로 연결돼 저장됩니다. |
| 작업 중에 사용자에게 질문할 수 없음 | 하위 에이전트는 clarify 도구를 쓸 수 없습니다. 대신 판단이 필요하면 `NEEDS_INPUT: <질문>`으로 답을 끝내도록 했습니다. 그러면 `status=needs_input`이 반환되고, 부모 세션이 clarify로 사용자에게 물어본 뒤 답을 넣어 다시 실행합니다. 실행 중인 하위 에이전트가 멈췄다가 이어서 진행하는 방식은 아닙니다. |

## 구성

```
source/jev-router/
  plugin.yaml, __init__.py      도구 2개, pre_tool_call hook, Skill 등록
  router.py                     검증, 저장, AA 이름 매핑, Jev 선택지 생성, 위젯 렌더링 (표준 라이브러리만 사용)
  widget.html                   허용 모델 체크 화면 템플릿
  skills/jev-model-router/      번들 Skill
  tests/                        단위 테스트 (router, AA 상태, hook·병렬 위임)
```

API 키, Hermes 설정, 대화 DB, 후보 표(`candidates.json`)는 저장소에 포함하지 않습니다.

## 새 Hermes 설치 후 복원

### 1. 준비
- Hermes, Git, GitHub CLI를 설치합니다. 이 비공개 저장소에 접근할 수 있는 계정으로 `gh auth login`을 하고, 이어서 `gh auth setup-git`을 실행합니다.
- 쓰려는 모델 provider를 Hermes에 로그인합니다(`hermes model` 또는 `hermes auth`). 후보 모델은 **이 단계에서 인증한 provider 안에서만** 고를 수 있습니다.
- TypeSafe API 키를 준비합니다(console.typesafe.ai). `uv`/`uvx`도 필요합니다.
- Artificial Analysis 무료 API 키를 발급받아(artificialanalysis.ai) `$HERMES_HOME/.env`에 `AA_API_KEY=...`로 넣습니다. 키가 없으면 Jev에게 잔량 정보만 보내게 되어 선택 품질이 떨어집니다.

### 2. Jev MCP 서버 등록
```text
hermes mcp add jev --command uvx --env TYPESAFE_API_KEY=<키> --args jev-mcp-server
hermes mcp test jev
```
키는 터미널에 직접 입력하세요. `--env`로 넣은 값은 `config.yaml`에 평문으로 저장됩니다.

### 3. 플러그인 설치·활성화
```text
hermes plugins install Gary-Y-Lee/Hermes_Plugin_00.Jev/source/jev-router --enable
hermes plugins list --plain --no-bundled
```
특정 버전을 재현하려면 `--ref <commit SHA>`를 붙입니다. 같은 이름의 플러그인이 이미 있으면 먼저 차이를 확인하세요. 무조건 `--force`로 덮어쓰지 않습니다.

### 4. 허용 모델 선택 (사용자 결정)
**새 세션**을 열고 이렇게 요청합니다.
```text
jev-model-router 설정해줘
```
설정을 시작하면 먼저 `AA_API_KEY` 등록 여부를 확인합니다(`jev_router_models action=status`, 키 값은 읽지 않음). 키가 없으면 Agent가 발급 방법을 안내하고 `.env` 파일을 메모장으로 열어 줍니다. 키를 저장한 뒤 다시 확인합니다. 키 없이 진행할 수도 있지만, 그러면 선택 화면 위쪽에 경고가 표시되고 Jev에게는 잔량 정보만 전달됩니다.

데스크톱 앱에서는 채팅 안에 **체크박스 선택 화면**이 나타납니다. provider별로 묶인 모델을 검색해 **쓸 수 있게 허용할 모델만 체크**하고 **저장**을 누르면 됩니다. tier 같은 등급은 정하지 않습니다. 화면에 참고용으로 모델마다 AA 점수, provider마다 구독 잔량이 표시되고, 이미 허용한 모델은 미리 체크돼 있습니다. 메신저나 CLI처럼 위젯을 띄울 수 없는 곳에서는 clarify 다중 선택으로 대신 고릅니다(질문 하나당 최대 4개). 저장할 때 이 환경의 모델 목록과 대조해 검증하며, 저장 위치는 `$HERMES_HOME/jev-router/candidates.json`(프로필별)입니다.

### 5. 사용
평소처럼 작업을 지시합니다. Skill이 `options` → Jev `choice`(작업 하나) 또는 `classify`(여러 작업, 1회) → `jev_delegate`(1회, 병렬) 순서로 실행하고, 어떤 모델이 선택됐는지와 Jev의 확신도, 차순위 모델을 함께 보고합니다. 간단한 질문은 하위 에이전트로 넘기지 않고 현재 세션이 바로 답합니다. "모델 X로 해줘"라고 하면 X로 바로 실행하는데, X는 허용 목록에 있어야 합니다.

## Jev에게 보내는 정보
선택지 하나는 허용 모델 하나이고, 설명은 다음과 같은 한 줄입니다.
```
anthropic/claude-opus-5-5: AA[Claude Opus 5.5 (Medium…)] 종합 51.2, 엔지니어링 53.7, 전략 57.5, 금융 54.1, 법률 57.4 | $4/$20/Mtok | 잔량 Current session 32% 남음, Current week 87% 남음
```
- **벤치마크**: AA 무료 API입니다. 종합·코딩·에이전트 지수와 엔지니어링·전략·금융·법률 영역 지수를 보내고, 값이 없는 항목은 뺍니다. 24시간 캐시합니다. 모델 이름은 규칙으로 변환합니다(예: `gpt-6.1-sol` → `gpt-6-1-sol-medium`).
- **effort 기준**: 하위 에이전트는 부모 세션의 reasoning effort를 그대로 씁니다. 그래서 점수도 config의 `reasoning_effort` 기준 값을 씁니다(기본 medium). 작업마다 effort를 바꾸는 기능은 아직 없습니다.
- **잔량**: `hermes usage --json`의 사용률로 계산한 남은 비율(%)입니다. 5분 캐시합니다. 토큰 수가 아니라 비율이고, copilot처럼 조회가 안 되는 provider는 "잔량 정보 없음"으로 표시합니다.
- **평가별 점수(선택)**: 무료 API에는 대부분 모델의 코딩·에이전트 지수가 없습니다. 그래서 사용자가 요청할 때만 Aside로 AA 비교 페이지를 읽어 `$HERMES_HOME/jev-router/aa-extra.json`(Git 제외, 개인 비상업 용도)에 Terminal-Bench, SciCode, GDPval 같은 점수를 저장하고, `options`가 이를 함께 보냅니다. 플러그인이 자동으로 수집하지는 않으며, 갱신 절차는 Skill에 있습니다. 새 PC에는 이 파일이 없으므로 필요하면 다시 요청하면 됩니다.
- **질문**: 작업 난이도와 중요도에 충분한 점수를 가진 모델 중 가장 저렴한 것을 고르되, 어렵거나 중요한 작업이면 상위 모델을 고르고, 잔량이 적은 모델은 피하라고 지시합니다.

## 테스트
```text
python -m unittest discover -s source/jev-router/tests -v
hermes plugins validate source/jev-router --json
hermes plugins doctor source/jev-router --ci
```

## 제약과 위험
- `jev_router_models`는 Hermes 내부 함수 `hermes_cli.model_switch_providers.list_authenticated_providers`를 사용합니다. validate에서 비공개 API라는 경고가 나오며, Hermes가 업데이트되면 동작하지 않을 수 있습니다. 이 경우 영향을 받는 건 모델 목록 조회와 저장할 때의 검증뿐이고, 라우팅과 실행은 그대로 동작합니다.
- AA 데이터는 Artificial Analysis 것입니다. 외부에 공개하거나 공유할 때는 출처를 표기해야 합니다. 모델 이름 변환 규칙이 AA 쪽 이름 변경과 맞지 않으면 "벤치마크 없음"으로 표시됩니다.
- 하위 에이전트는 부모 세션보다 적은 도구만 쓸 수 있고 메모리가 없습니다. 필요한 경로와 규칙은 `context`에 담아 전달해야 합니다.
- 하위 에이전트 결과는 Hermes 프로세스가 실행 중일 때만 유지됩니다(`subagent_lifecycle`의 제약).
- `delegate_task`에는 작업별 모델 필드가 없어 hook으로 인자만 바꿀 수 없습니다. 그래서 hook은 차단 후 안내하는 방식이며, 위임할 때마다 첫 `delegate_task` 시도 1회가 차단 응답으로 소비됩니다.
- `jev_delegate`는 `output_schema`를 지원하지 않습니다. 출력 형식은 `context`에 적고 결과 파일은 부모 세션이 확인합니다.
- 동시 실행은 Hermes lifecycle 실행기 한도(8개)를 따릅니다. 그보다 많으면 나머지는 대기 후 실행됩니다.
- hook을 끄려면 `candidates.json`의 허용 모델을 비우거나 플러그인을 비활성화합니다(`hermes plugins disable jev-router`).
- 저장소를 복원할 수 있다는 것이 새 PC에서 로그인, Jev 키, 실제 작업까지 성공한다는 보장은 아닙니다.
