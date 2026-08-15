#!/usr/bin/env bash
#
# G-LOCAL. 판정 대상 저장소의 변경분에 어떤 점검 항목이 걸리는지 계산한다.
#
# LLM 을 부르지 않는다. 판정은 이 출력을 받은 Claude 가 한다.
# Gemini 는 CI 의 G-PR 에서만 돈다. 무료 티어 한도를 로컬이 나눠 쓰면
# 작업 중 반복 실행하는 것만으로 CI 가 밀린다.
#
#   ./verify.sh                     마지막 커밋 하나
#   ./verify.sh HEAD~5              지정한 지점부터 HEAD 까지
#   ./verify.sh <base> <head>       범위를 직접 준다
#   ./verify.sh --target ../fm-infra   판정 대상을 바꾼다 (기본은 현재 디렉터리)
#
# 차단하지 않는다. 작업 중 반복 실행하는 도구이므로 중간 상태에서 위반이 나오는 것이 정상이다.

set -u

# --- 인자 ---------------------------------------------------------------
TARGET=$PWD
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET=$2; shift 2 ;;
        -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
BASE=${ARGS[0]:-HEAD~1}
HEAD_REF=${ARGS[1]:-HEAD}

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

echo "판정 대상 $TARGET"
echo "기준      common=$COMMON"
echo "          infra=$INFRA"
echo "범위      $BASE..$HEAD_REF"
echo

# --- 1. 빌드 게이트 -----------------------------------------------------
# CI 에서는 이 둘이 병합을 차단한다. 여기서는 알리기만 한다.
#   *.domain.service.* 메서드 커버리지 100%
#   정적 분석 신규 Blocker 0건
if [ -x "$TARGET/gradlew" ]; then
    echo "== 빌드 게이트"
    if (cd "$TARGET" && ./gradlew check --no-daemon -q); then
        echo "통과"
    else
        echo "미달. CI 에서는 여기서 병합이 막힌다"
    fi
    echo
fi

# --- 2. 대상 항목 계산 ------------------------------------------------
# run.py --mode match 는 앵커 규칙만 돌린다. 네트워크도 API 키도 쓰지 않는다.
# --mode judge 는 Gemini 를 부르므로 여기서 쓰지 않는다.
echo "== 대상 항목"
python3 "$COMMON/.github/llm-verify/run.py" --mode match \
    --backend "$TARGET" --common "$COMMON" --infra "$INFRA" \
    --base "$(cd "$TARGET" && git rev-parse "$BASE")" \
    --head "$(cd "$TARGET" && git rev-parse "$HEAD_REF")"

echo
echo "판정은 이 출력을 받은 Claude 가 한다. 이 스크립트는 LLM 을 부르지 않는다."
