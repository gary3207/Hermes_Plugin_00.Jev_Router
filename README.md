# Hermes_Plugin_00.Jev

이 플러그인은 TypeSafe **Jev**로 작업 하나하나를 분류하고, 그 결과에 따라 **사용자가 고른 후보 모델** 중 하나로 작업을 실행합니다. 실행은 Hermes의 하위 에이전트(subagent)로 하며, 이 하위 에이전트는 현재 세션에 연결됩니다. 원본 작업 세션은 `20261015_181657_b4fee8`과 이 플러그인을 만든 세션입니다.

- **`jev_router_models`**: 지금 설치된 Hermes에서 인증된 provider와 모델 목록을 조회하고, 사용자가 고른 후보 표를 보여주거나 저장합니다. 그래서 PC나 구독이 달라도 그 환경에서 실제로 쓸 수 있는 모델로 다시 고르면 됩니다.
- **`jev_delegate`**: Jev가 붙인 분류 결과(task_type, difficulty, quality_critical, confidence)와 후보 표를 보고 모델을 정합니다. 계산 방식이 고정돼 있어 같은 입력이면 항상 같은 모델이 나옵니다. 그 모델로 하위 에이전트를 실행합니다(공개 플러그인 API `ctx.subagent_lifecycle`).
- **Skill `jev-router:jev-model-router`**: 처음 설정하는 방법, Jev 질문 방식, 작업 중 질문 처리 절차를 담고 있습니다.

### 두 가지 제약을 이렇게 해결합니다
| 제약 | 해결 방법 |
|---|---|
| 작업마다 모델을 바꿀 수 없음 | `subagent_lifecycle.launch(provider, model)`로 실행할 때마다 모델을 지정합니다. 전역 config는 바꾸지 않습니다. |
| 세션 기록이 따로 남음 | 하위 에이전트가 같은 세션 DB에 `parent_session_id`로 연결돼 저장됩니다. |
| 작업 중에 사용자에게 질문할 수 없음 | 하위 에이전트는 clarify 도구를 쓸 수 없습니다. 대신 판단이 필요하면 `NEEDS_INPUT: <질문>`으로 답을 끝내도록 했습니다. 그러면 `status=needs_input`이 반환되고, 부모 세션이 clarify로 사용자에게 물어본 뒤 답을 넣어 다시 실행합니다. 실행 중인 하위 에이전트가 멈췄다가 이어서 진행하는 방식은 아닙니다. |

## 구성

```
source/jev-router/
  plugin.yaml, __init__.py      도구 2개와 Skill 등록
  router.py                     라우팅, 검증, 저장 로직 (표준 라이브러리만 사용)
  skills/jev-model-router/      번들 Skill
  tests/test_router.py          단위 테스트
```

API 키, Hermes 설정, 대화 DB, 후보 표(`candidates.json`)는 저장소에 포함하지 않습니다.

## 새 Hermes 설치 후 복원

### 1. 준비
- Hermes, Git, GitHub CLI를 설치합니다. 이 비공개 저장소에 접근할 수 있는 계정으로 `gh auth login`을 하고, 이어서 `gh auth setup-git`을 실행합니다.
- 쓰려는 모델 provider를 Hermes에 로그인합니다(`hermes model` 또는 `hermes auth`). 후보 모델은 **이 단계에서 인증한 provider 안에서만** 고를 수 있습니다.
- TypeSafe API 키를 준비합니다(console.typesafe.ai). `uv`/`uvx`도 필요합니다.

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

### 4. 후보 모델 선택 (사용자 결정)
**새 세션**을 열고 이렇게 요청합니다.
```text
jev-model-router 설정해줘
```
Agent가 `jev_router_models action=available`로 이 환경에서 쓸 수 있는 모델을 보여줍니다. 사용자는 후보 모델과 각 모델의 tier를 고릅니다(1 가벼움·빠름, 2 표준, 3 최고 성능). 필요하면 업무 유형별 선호도 지정합니다. 저장할 때 이 환경의 모델 목록과 대조해 검증하며, 저장 위치는 `$HERMES_HOME/jev-router/candidates.json`(프로필별)입니다.

### 5. 사용
평소처럼 작업을 지시합니다. Skill이 Jev로 작업을 분류하고, `jev_delegate`로 실행한 뒤 어떤 모델이 왜 선택됐는지 함께 보고합니다. 간단한 질문은 하위 에이전트로 넘기지 않고 현재 세션이 바로 답합니다. "모델 X로 해줘"라고 하면 `override_model`이 적용되는데, 이때 X는 저장된 후보여야 합니다.

## 라우팅 규칙
- 필요 tier는 difficulty 1~2이면 1, 3이면 2, 4~5이면 3입니다.
- quality_critical이면 3으로 올립니다.
- confidence가 0.6 미만이면 한 단계 올립니다(최대 3).
- 해당 tier의 후보가 없으면 가장 가까운 상위 tier, 그것도 없으면 가장 가까운 하위 tier를 고릅니다.
- 같은 tier 안에서는 `tasks`에 해당 업무 유형이 있는 후보, 범용 후보, 표 순서 순으로 고릅니다.

## 테스트
```text
python -m unittest discover -s source/jev-router/tests -v
hermes plugins validate source/jev-router --json
hermes plugins doctor source/jev-router --ci
```

## 제약과 위험
- `jev_router_models`는 Hermes 내부 함수 `hermes_cli.model_switch_providers.list_authenticated_providers`를 사용합니다. validate에서 비공개 API라는 경고가 나오며, Hermes가 업데이트되면 동작하지 않을 수 있습니다. 이 경우 영향을 받는 건 모델 목록 조회와 저장할 때의 검증뿐이고, 라우팅과 실행은 그대로 동작합니다.
- 하위 에이전트는 부모 세션보다 적은 도구만 쓸 수 있고 메모리가 없습니다. 필요한 경로와 규칙은 `context`에 담아 전달해야 합니다.
- 하위 에이전트 결과는 Hermes 프로세스가 실행 중일 때만 유지됩니다(`subagent_lifecycle`의 제약).
- 저장소를 복원할 수 있다는 것이 새 PC에서 로그인, Jev 키, 실제 작업까지 성공한다는 보장은 아닙니다.
