# G-LOCAL 판정 절차

**도구에 매이지 않는 문서다.** Claude Code, 다른 CLI 에이전트, 사람 누구든 이 절차를 따르면 된다.
도구별 진입점(`.claude/commands/v-commit.md` 등)은 이 문서를 가리키기만 한다.

계산은 `verify.sh` 가 하고 **판정은 이 문서를 읽는 쪽이 한다.**
LLM API 를 부르는 것은 CI 의 G-PR 뿐이다. 여기서는 API 를 쓰지 않는다.

**차단하지 않는다.** 작업 중 반복 실행하는 도구이므로 중간 상태에서 위반이 나오는 것이 정상이다.

## 1. 계산을 돌린다

```bash
./verify.sh          # 아직 push 하지 않은 커밋 전부
./verify.sh HEAD     # HEAD 커밋 하나
./verify.sh HEAD~1   # 그 앞 커밋 하나
./verify.sh <SHA>    # 그 커밋 하나
./verify.sh -n 5     # 최신 5개
```

**ref 는 언제나 git 이 읽는 그대로다.** 개수를 볼 때만 `-n` 을 쓴다.
ref 하나를 주면 그 커밋 하나를 본다. `<ref>~1..<ref>` 로 푼다.

두 개를 주면 `<base> <head>` 구간을 그대로 쓴다. 지난 구간을 다시 볼 때만 쓴다.

인자를 안 주면 upstream 과의 차이를 본다. upstream 이 없으면 `origin/HEAD` 를 쓰고,
그것도 없으면 범위를 정할 수 없어 종료 코드 `2` 로 멈춘다.

저장소 루트의 `verify.sh` 가 진입점이다. common 저장소를 찾아 본체를 부르고,
본체가 빌드 게이트를 돌리고 이번 변경에 걸리는 앵커 규칙을 계산한 뒤 **이 지시문을 낸다.**

이 문서를 읽고 있다면 그 단계는 이미 끝났다. 지시문에 계산 결과가 함께 들어 있다.

```json
{"needs_baseline": "false", "rules": "on_no_match", "changed": "11"}
```

| 값 | 뜻 |
|---|---|
| `rules` | 걸린 앵커 규칙 목록. 이것이 판정할 항목을 정한다 |
| `needs_baseline` | `true` 면 확정값 문서를 함께 읽어야 한다 |
| `changed` | 변경 파일 수 |

종료 코드 `2` 는 기준 저장소를 못 찾은 것이다. 그때는 판정하지 않는다.

## 2. 판정에 필요한 것을 읽는다

### 앵커 파일

3단계가 정한 `anchors` 글롭에 맞는 파일을 **diff 에 없어도** 읽는다.

이것이 부재 판정의 근거다. "타임아웃 설정이 없다" 를 말하려면 설정이 있을 법한 파일을 봐야 한다.
읽지 못한 앵커가 있으면 그 앵커에 의존하는 항목은 `INSUFFICIENT_EVIDENCE` 로 둔다. **통과시키지 않는다.**

### 확정값

매칭된 규칙 중 하나라도 `needs_baseline_values: true` 면 `$INFRA/docs/system-design/` 의 문서를 읽는다.
아니면 읽지 않는다.

### 알려진 모순

`$COMMON/.github/llm-verify/known-conflicts.yml` 을 읽는다.

* `status: unresolved` 인 모순의 `affects` 에 있는 항목은 `CONFLICTING_BASELINE` 으로 두고 **양쪽 값을 함께 표기**한다. 한쪽을 골라 판정하지 않는다.
* `status: intentional` 은 모순이 아니다. `sources` 의 뒤쪽(확정값)을 기준으로 판정한다.
* 목록에 없는 모순을 발견하면 **새로 발견된 것이므로 보고**한다.

### 판정 기준 본문

활성 항목이 속한 문서만 읽는다. 각 항목의 `doc` 필드가 파일명이다.

```
$COMMON/docs/software-quality/qa-*.md
docs/code-architecture/*-guideline.md
$INFRA/docs/infra-review/code-guideline.md
```

ID 와 제목만으로 판정하지 않는다. **본문에 판정 기준과 예외가 적혀 있다.**

## 3. 판정한다

활성 항목 하나하나에 대해 `verdict` 를 정한다.

| 값 | 언제 |
|----|------|
| `VIOLATION` | 위반을 확인했다 |
| `OK` | 충족을 확인했다 |
| `NOT_APPLICABLE` | 이 변경과 무관하다 |
| `INSUFFICIENT_EVIDENCE` | 판정에 필요한 증거가 입력에 없다 |
| `CONFLICTING_BASELINE` | 확정값이 문서마다 다르다 |

`UNJUDGED` 는 쓰지 않는다. 로컬에서는 활성 항목을 전부 판정하므로 이 값이 나올 자리가 없다.

**추측으로 `OK` 를 내지 않는다.** 근거 파일을 못 봤으면 `INSUFFICIENT_EVIDENCE` 다.
이 구분이 무너지면 게이트가 통과시킨 것과 안 본 것이 뒤섞여 지표가 무의미해진다.

### 설명은 한국어로 쓴다

점검 항목과 판정 기준이 한국어이므로 지적도 한국어여야 대조하기 쉽다.

**다만 아래는 원문 그대로 둔다.** 번역하면 검색과 대조가 깨진다.

```
항목 ID          SEC-1-01,  BLD-1-03
verdict          VIOLATION,  OK,  NOT_APPLICABLE,  INSUFFICIENT_EVIDENCE,  CONFLICTING_BASELINE
파일 경로         src/main/java/com/x/domain/service/OrderService.java
클래스와 메서드    OrderService.pay
설정 키와 값      maximum-pool-size: 10,  @Transactional
점검 항목 제목     문서에 적힌 문장 그대로
```

예를 들면 이렇게 쓴다.

```
SEC-1-01  리소스 접근 시 소유권 또는 권한을 검증하는가
  기준: common `qa-security.md` 1장
  OrderService.java:4
  id 로 조회만 하고 호출자가 소유자인지 확인하지 않는다
  인증 주체의 식별자를 조회 조건에 포함한다
```

### 중복 지적 억제

항목에 `defers_to` 가 있으면, 그 대상 항목이 같은 코드에 대해 `VIOLATION` 이면 **이쪽은 발화하지 않는다.**
같은 문제를 두 번 지적하면 리뷰 신뢰도가 떨어진다.

## 4. 출력

```
G-LOCAL  <커밋 SHA 앞 7자리>  <메시지>

빌드 게이트
  커버리지   <통과 또는 미달 목록>
  정적 분석  <통과 또는 Blocker 목록>

매칭된 규칙  <규칙 id 나열>
활성 항목    <n>건  (backend <a>, common <b>, infra <c>)

VIOLATION <n>건
  <ID>  <제목>
    기준: <저장소> <doc> <ch>장
    파일:줄
    무엇이 문제인가 한 줄
    어떻게 고치는가 한 줄

CONFLICTING_BASELINE <n>건
  <ID>  <제목>  (기준: <저장소> <doc> <ch>장)
    <문서 A>: <값>
    <문서 B>: <값>
    -> 결정 필요

INSUFFICIENT_EVIDENCE <n>건
  <ID>  <제목>  (기준: <저장소> <doc> <ch>장)  못 읽은 앵커: <경로>

OK <n>  NOT_APPLICABLE <n>
```

`VIOLATION` 만 자세히 쓰고 나머지는 건수와 ID 만 낸다.

**기준 줄은 빼지 않는다.** 항목 ID 와 제목만 주면 받는 쪽이 근거 본문을 찾을 수 없다.
항목이 세 저장소에 흩어져 있어서 어느 저장소인지부터 알아야 한다.
`doc` 과 `ch` 는 `items.yml` 에 이미 있으므로 옮겨 적기만 하면 된다.
`INSUFFICIENT_EVIDENCE` 가 계속 같은 항목에서 나오면 `anchors.yml` 의 앵커 목록이 부족한 것이므로 그 사실을 함께 말한다.

## 5. 기록

화면에 낸 것과 **같은 내용**을 파일로 남긴다. 요약해서 저장하지 않는다.

```bash
mkdir -p docs/llm-review
LOGIN=$(gh api user -q .login 2>/dev/null || git config user.name)
STAMP=$(date +%Y%m%d-%H%M%S)
echo "docs/llm-review/${LOGIN}_${STAMP}_llm-review.md"
```

파일명은 `<깃허브 계정명>_<YYYYMMDD-HHMMSS>_llm-review.md` 다.
계정명을 넣는 이유는 팀원이 각자 로컬에서 돌리기 때문이고,
초 단위까지 넣는 이유는 한 커밋을 고쳐 가며 여러 번 돌리는 것이 정상 사용이기 때문이다.

`gh` 인증이 없으면 `git config user.name` 으로 떨어진다. 둘 다 없으면 `unknown` 을 쓰고 그 사실을 알린다.

파일 첫머리에 다시 만들 수 있는 정보를 넣는다. 없으면 나중에 이 기록이 무엇을 판정한 것인지 알 수 없다.

```markdown
---
검증: G-LOCAL
계정: <계정명>
시각: <ISO 8601>
저장소: <origin URL>
브랜치: <브랜치명>
커밋: <전체 SHA>
범위: <base>..<head>
기준 저장소:
  common: <커밋 SHA>  <경로>   # 옆 저장소인지 캐시인지 적는다
  infra: <커밋 SHA>  <경로>
매칭 규칙: [<규칙 id>]
활성 항목: <n> (backend <a>, common <b>, infra <c>)
---
```

**기준 저장소의 SHA 를 남기는 것이 핵심이다.**
점검 항목은 계속 바뀌므로, 어느 시점의 기준으로 판정했는지 모르면 과거 기록을 다시 읽을 수 없다.

경로도 함께 적는다. 옆 저장소를 썼는지 캐시를 썼는지에 따라 기준이 다를 수 있고,
캐시가 낡아 있었다면 그 기록만 보고도 알 수 있어야 한다.

저장 후 경로를 한 줄로 알린다.

```
기록: docs/llm-review/devjohnpark_20260806-174500_llm-review.md
```

### 이 디렉터리를 커밋하는가

**커밋한다.** 두 가지 이유다.

* 계정명으로 파일을 나누는 것은 여러 사람이 볼 때만 의미가 있다
* 로컬 판정은 재량이라 안 돌려도 아무 일이 없다. 기록이 남아야 돌렸는지가 구분된다

두 번째가 G-AUDIT 으로 이어질 자리이지만, **아직 이것을 점검하는 항목은 등록되어 있지 않다.**
넣으려면 `docs/software-quality/` 에 항목을 추가하고 `items.yml` 을 다시 생성해야 한다.

파일명이 계정과 초 단위 시각을 포함하므로 충돌하지 않는다.
쌓이는 속도가 부담스러워지면 분기별로 정리하되, **지우기 전에 G-AUDIT 주기를 확인한다.**

## CI 와 다른 점

| | G-LOCAL (이 명령) | G-PR (CI) |
|---|---|---|
| 판정 주체 | Claude | gemini-2.5-flash |
| 범위 | push 하지 않은 커밋 (인자로 조절) | PR 누적 diff |
| 단계 | 없음. 활성 항목 전부 | 1단계 backend, 2단계 common+infra 조건부 |
| 차단 | 안 함 | 안 함 |

**로컬을 건너뛰고 CI 2단계가 실패하면 common 과 infra 기준은 아무도 보지 않는다.**
그 조합이 실제로 일어나므로 커밋 후 이 명령을 돌리는 것이 권장된다.
