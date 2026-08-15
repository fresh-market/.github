#!/usr/bin/env bash
#
# G-LOCAL 본체. 판정 범위를 계산하고 판정 지시문을 만든다.
#
# LLM API 를 부르지 않는다. 판정은 지시문을 받은 CLI 에이전트가 한다.
# Gemini API 는 CI 의 G-PR 에서만 돈다. 무료 티어 한도를 로컬이 나눠 쓰면
# 작업 중 반복 실행하는 것만으로 CI 가 밀린다.
#
#   verify.sh                      전체. 아직 push 하지 않은 커밋 전부
#   verify.sh HEAD                 최신 커밋 1개
#   verify.sh HEAD~5               최신 커밋 5개
#   verify.sh <base> <head>        두 개를 주면 그 구간을 그대로 쓴다
#   verify.sh --agent claude       지시문을 그 명령에 넘긴다
#   verify.sh --agent "gemini -p"  임의의 CLI 에 넘긴다
#   verify.sh --target ../fm-infra 판정 대상을 바꾼다 (기본은 현재 디렉터리)
#
# 차단하지 않는다. 작업 중 반복 실행하는 도구이므로 중간 상태에서 위반이 나오는 것이 정상이다.

set -u

# --- 인자 ---------------------------------------------------------------
TARGET=$PWD
AGENT=""
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET=$2; shift 2 ;;
        --agent)  AGENT=$2;  shift 2 ;;
        -h|--help) sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
# 인자는 "몇 개" 를 뜻한다. git 의 base..head 와 다르게 읽는다.
#   없음      전체. 아직 push 하지 않은 커밋 전부
#   HEAD      최신 1개    -> HEAD~1..HEAD
#   HEAD~N    최신 N개    -> HEAD~N..HEAD
#   둘을 주면 그 구간을 그대로 쓴다
HEAD_REF=${ARGS[1]:-HEAD}
if [ ${#ARGS[@]} -eq 0 ]; then
    BASE=""
elif [ ${#ARGS[@]} -ge 2 ]; then
    BASE=${ARGS[0]}
elif [ "${ARGS[0]}" = "HEAD" ]; then
    BASE=HEAD~1
else
    BASE=${ARGS[0]}
fi

# --- 기준 저장소 --------------------------------------------------------
# common 은 이 스크립트가 들어 있는 저장소다. 이름을 알 필요가 없다.
COMMON=$(cd "$(dirname "$0")/../.." && pwd)

# infra 는 items.yml 의 source 필드로 찾는다. 디렉터리 이름을 보지 않는다.
#
# 글롭 대신 find 를 쓰는 이유가 둘이다.
#   common 저장소의 기본 clone 이름이 .github 라 숨김 디렉터리가 되는데 */ 가 건너뛴다.
#   .*/ 를 더하면 zsh 에서 매칭이 없을 때 no matches found 로 죽는다.
# 파이프 대신 프로세스 치환을 쓰는 이유는, 파이프로 while 을 돌리면 서브셸이라
# INFRA 가 바깥으로 전달되지 않기 때문이다.
INFRA=${INFRA:-}
while IFS= read -r f; do
    if [ "$(sed -n 's/^source: *//p' "$f" | head -1)" = "infra" ]; then
        INFRA=$(cd "$(dirname "$f")/../.." && pwd)
    fi
done < <(find "$COMMON/.." -maxdepth 4 -path '*/.github/llm-verify/items.yml' 2>/dev/null)

: "${INFRA:=$HOME/.cache/llm-verify/infra}"

for d in "$TARGET" "$COMMON" "$INFRA"; do
    if [ ! -f "$d/.github/llm-verify/items.yml" ]; then
        echo "기준 저장소를 찾지 못했다: $d/.github/llm-verify/items.yml" >&2
        echo "옆에 clone 하거나 ~/.cache/llm-verify/ 에 두어야 한다." >&2
        exit 2
    fi
done

# 인자가 없으면 push 하지 않은 구간 전부를 본다.
# upstream 이 없으면 origin/HEAD 와 비교하고, 그것도 없으면 범위를 정할 수 없다.
if [ -z "$BASE" ]; then
    if (cd "$TARGET" && git rev-parse --verify -q '@{u}' >/dev/null 2>&1); then
        BASE='@{u}'
    elif (cd "$TARGET" && git rev-parse --verify -q origin/HEAD >/dev/null 2>&1); then
        BASE='origin/HEAD'
    else
        echo "전체 범위를 정할 수 없다. upstream 도 origin/HEAD 도 없다." >&2
        echo "HEAD 나 HEAD~N 으로 범위를 직접 준다." >&2
        exit 2
    fi
fi

BASE_SHA=$(cd "$TARGET" && git rev-parse "$BASE")
HEAD_SHA=$(cd "$TARGET" && git rev-parse "$HEAD_REF")

echo "판정 대상 $TARGET"
echo "기준      common=$COMMON"
echo "          infra=$INFRA"
N=$(cd "$TARGET" && git rev-list --count "$BASE_SHA..$HEAD_SHA")
echo "범위      $BASE_SHA..$HEAD_SHA  (커밋 ${N}개)"
echo

# --- 1. 빌드 게이트 -----------------------------------------------------
# CI 에서는 이 둘이 병합을 차단한다. 여기서는 알리기만 한다.
#   *.domain.service.* 메서드 커버리지 100%
#   정적 분석 신규 Blocker 0건
BUILD_RESULT="건너뜀 (gradlew 없음)"
if [ -x "$TARGET/gradlew" ]; then
    if (cd "$TARGET" && ./gradlew check --no-daemon -q); then
        BUILD_RESULT="통과"
    else
        BUILD_RESULT="미달. CI 에서는 여기서 병합이 막힌다"
    fi
fi
echo "== 빌드 게이트"
echo "$BUILD_RESULT"
echo

# --- 2. 대상 항목 계산 --------------------------------------------------
# run.py --mode match 는 앵커 규칙만 돌린다. 네트워크도 API 키도 쓰지 않는다.
# --mode judge 는 Gemini 를 부르므로 여기서 쓰지 않는다.
SCOPE=$(python3 "$COMMON/.github/llm-verify/run.py" --mode match \
    --backend "$TARGET" --common "$COMMON" --infra "$INFRA" \
    --base "$BASE_SHA" --head "$HEAD_SHA")

# --- 3. 판정 지시문 -----------------------------------------------------
# 절차 본문은 담지 않는다. 문서를 가리키기만 해서 절차가 한 곳에만 있게 한다.
PROMPT=$(cat <<EOF
$COMMON/docs/verification/g-local.md 의 절차대로 G-LOCAL 판정을 수행하라.

판정 대상   $TARGET
범위        $BASE_SHA..$HEAD_SHA  (커밋 ${N}개)
기준        common=$COMMON
            infra=$INFRA
계산 결과   $SCOPE
빌드 게이트  $BUILD_RESULT

계산(1장)은 끝났다. 2장부터 진행하라.
EOF
)

if [ -n "$AGENT" ]; then
    printf '%s\n' "$PROMPT" | $AGENT
else
    echo "== 판정 지시문"
    printf '%s\n' "$PROMPT"
    echo
    echo "쓰는 CLI 에이전트에 넘기면 된다. --agent <명령> 으로 바로 넘길 수도 있다."
fi
