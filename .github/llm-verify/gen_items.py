#!/usr/bin/env python3
"""
점검 항목 레지스트리 생성기.

가이드 문서가 원본이고 items.yml 은 파생물이다. 문서를 고치면 이것을 다시 돌린다.
items.yml 을 직접 고치면 다음 생성 때 조용히 덮어써진다.

    python3 gen_items.py <문서 디렉터리> <글롭> <source> [기본 층위] [-o 출력파일]

    # common. 층위 태그가 문서에 있다
    python3 gen_items.py ../../docs/software-quality 'qa-*.md' common \\
            -o items.yml

    # backend, infra. 태그가 없어 기본값을 준다
    # 경로는 예시가 아니라 자리표시다. 저장소 이름은 바뀌므로 여기에 적지 않는다
    python3 gen_items.py <backend 경로>/docs/code-architecture '*-guideline.md' backend 코드 \\
            -o <backend 경로>/.github/llm-verify/items.yml
    python3 gen_items.py <infra 경로>/docs/infra-review '*-guideline.md' infra 코드 \\
            -o <infra 경로>/.github/llm-verify/items.yml

읽는 형식은 두 가지다.

    점검 항목
    * `[코드]` `REL-2-01` 제목            <- common. 층위 태그가 앞에 붙는다
    * `EJ-1-01` 제목 (아이템 1)           <- backend, infra
      들여쓴 줄은 부연 설명이라 항목이 아니다

`점검 항목` 이라는 줄에서 블록이 시작하고 빈 줄에서 끝난다.
들여쓴 줄에서 끝나지 않는다. 부연 설명이 항목 사이에 끼기 때문이다.

--check 를 주면 파일을 쓰지 않고 기존 것과 같은지만 본다. CI 에서 이걸 돌리면
문서를 고치고 레지스트리를 재생성하지 않은 PR 을 잡을 수 있다.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

# 층위가 판정 시점을 정하고, 판정 시점이 게이트를 정한다.
# 코드와 인프라는 파일을 읽어 판정하므로 PR 에서 본다.
# 설계는 구현 전에 봐야 하고, 프로세스와 운영은 기록으로만 확인되며,
# 실행 전은 런타임 조회가 필요해 스크립트가 판정한다.
GATE = {
    "코드": "G-PR",
    "인프라": "G-PR",
    "설계": "G-DESIGN",
    "프로세스": "G-AUDIT",
    "운영": "G-AUDIT",
    "실행전": "G-RELEASE",
}

# 문서 이름이 층위를 정하는 경우. infra 는 판정 주체별로 파일을 나눴다
LEVEL_BY_DOC = {
    "preflight-guideline.md": "실행전",
    "operation-guideline.md": "운영",
}

# 검증 설계 문서는 게이트 자체를 점검하는 항목(LLM-*)을 담고 있으나 판정 대상이 아니다.
# 글롭에 걸리므로 명시적으로 뺀다
EXCLUDE = {"qa-llm-verification.md"}

# CI 를 두 단계로 나눈다. 1단계는 항상 돌고 2단계는 1단계가 온전할 때만 돈다.
# gemini-2.5-flash 무료 티어가 464건을 한 번에 처리하는지 측정된 바 없기 때문이다
CI_STAGE = {"backend": 1, "common": 2, "infra": 2}

# 어느 영역의 관심사인가. 판정에 쓰지 않고 집계와 검색에 쓴다
DOMAINS = {
    "API": ["application"], "BE": ["database"], "BLD": ["application"],
    "CMP": ["application"],
    "DI": ["database"], "DPB": ["application"], "EC": ["application", "database"],
    "EJ": ["application"], "FLX": ["application", "infra"], "FUN": ["application"],
    "IDS": ["database", "security"], "INC": ["infra"], "INF": ["application", "infra"],
    "JPA": ["database"], "MNT": ["application"], "OBS": ["application", "infra"],
    "OPS": ["infra"], "PERF": ["application", "database", "infra"], "PRE": ["infra"],
    "REL": ["application", "infra"], "SEC": ["security"],
    "TRD": ["application", "security", "database", "infra"], "UT": ["application"],
}

# 접두사 기본값에서 벗어나는 항목
DOMAIN_OVERRIDE = {
    "DI-6-04": ["database", "infra"],
    "MNT-5-01": ["application", "infra"],
    "MNT-5-02": ["application", "infra"],
    "SEC-6-01": ["security", "infra"],
    "SEC-6-02": ["security", "infra"],
}

# 중복 지적 방지. 대상 항목이 위반이면 이쪽은 발화하지 않는다.
# 근거는 fresh-market/fm-infra 의 INFRAREVIEW.md "중복 지적 방지" 절에 있다
DEFERS = {
    "DI-2-01": ["INF-1-04", "INF-1-05"],
    "DI-2-02": ["INF-1-08"],
    "DI-4-03": ["INF-1-07"],
    "FLX-2-01": ["INF-2-01", "INF-2-02"],

    # 베이스 엔티티와 식별자 전략이 겹치는 지점.
    # "어느 베이스를 상속하는가" 는 BE 가, "public_id 가 필요한가" 는 IDS 가 소유한다.
    # CODEREVIEW.md 의 소유권 표를 따른다
    "BE-1-04": ["IDS-2-03"],

    # 스키마 변경을 호환성 문서와 유연성 문서가 각각 다루어 세 쌍이 겹친다.
    # 두 장을 합치는 것이 옳으나 문서 재구성은 별건이라, 우선 발화만 하나로 줄인다.
    # 더 구체적인 쪽이 말한다: 이 인프라의 확정 규칙 > 조건이 붙은 일반론 > 일반론
    "CMP-5-02": ["INF-6-01", "FLX-5-01"],   # 컬럼 제거 단계
    "FLX-5-01": ["INF-6-01"],
    "CMP-5-04": ["FLX-5-02"],               # 온라인 DDL. FLX 는 대용량 조건이 붙어 더 구체적
    "FLX-5-03": ["CMP-5-01"],               # 롤백. CMP 는 양방향 강제 없음까지 본다
}

ITEM = re.compile(
    r"^\*\s+"                              # 목록 표시
    r"(?:`\[(?P<level>[^\]]+)\]`\s+)?"     # 층위 태그. common 에만 있다
    r"`(?P<id>[A-Z]+-\d+-\d+)`\s+"         # 항목 ID
    r"(?P<title>.+?)\s*$"
)


def parse(path, default_level):
    """
    `점검 항목` 블록에서 항목을 뽑는다.

    항목 줄 아래의 들여쓴 줄은 그 항목의 판정 기준이다. 함께 담는다.
    담지 않으면 판정할 때마다 가이드 문서 전체를 실어야 하는데,
    그중 판정에 쓰이는 것은 이 줄들뿐이고 나머지 75% 는 배경 서술과 예시다.
    """
    items, inside = [], False
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines):
        if line.strip() == "점검 항목":
            inside = True
            continue
        if not inside:
            continue
        # 빈 줄에서 블록이 끝난다. 들여쓴 줄은 부연 설명이라 계속 읽는다
        if not line.strip():
            inside = False
            continue
        m = ITEM.match(line)
        if not m:
            continue
        criteria = []
        for follow in lines[n + 1:]:
            if not follow.startswith("  ") or not follow.strip():
                break
            criteria.append(follow.strip())
        level = m.group("level") or LEVEL_BY_DOC.get(path.name) or default_level
        if not level:
            sys.exit(f"층위를 알 수 없다: {path.name} {m.group('id')}")
        if level not in GATE:
            sys.exit(f"모르는 층위 '{level}': {path.name} {m.group('id')}")
        items.append({
            "id": m.group("id"),
            "doc": path.name,
            "ch": int(m.group("id").split("-")[-2]),
            "level": level,
            "title": m.group("title"),
            "criteria": " ".join(criteria),
        })
    return items


def quote(s):
    # 제목 안의 큰따옴표는 작은따옴표로 바꾼다. 이스케이프하면 한 줄 표기가 읽기 어려워진다
    return '"' + s.replace("\\", "\\\\").replace('"', "'") + '"'


def build(root, pattern, source, default_level):
    items = []
    for path in sorted(Path(root).glob(pattern)):
        if path.name in EXCLUDE:
            continue
        items += parse(path, default_level)

    seen = {}
    for it in items:
        if it["id"] in seen:
            sys.exit(f"ID 중복: {it['id']} ({seen[it['id']]}, {it['doc']})")
        seen[it["id"]] = it["doc"]

    unknown = {prefix_of(i["id"]) for i in items} - set(DOMAINS)
    if unknown:
        sys.exit(f"DOMAINS 에 없는 접두사: {sorted(unknown)}")

    # 정렬하지 않는다. 문서에 적힌 순서가 곧 레지스트리 순서다.
    # 정렬하면 문서와 대조하기 어려워지고, 항목을 문서 중간에 끼워 넣을 때
    # 레지스트리 전체가 재배치되어 diff 가 커진다.

    tagged = default_level is None
    out = [
        f"# {source} 점검 항목 레지스트리",
        "# 문서에서 자동 생성한다. 직접 편집하지 않는다.",
        f"# 생성 명령: gen_items.py <dir> '{pattern}' '{source}'"
        + ("" if tagged else f" {default_level}"),
        "version: 1",
        f"source: {source}",
        f"count: {len(items)}",
        "items:",
    ]
    for it in items:
        prefix = prefix_of(it["id"])
        f = [
            f"id: {it['id']}",
            f"doc: {it['doc']}",
            f"ch: {it['ch']}",
            f"level: {it['level']}",
            f"gate: {GATE[it['level']]}",
            "gates: [local, ci]",
            f"ci_stage: {CI_STAGE[source]}",
        ]
        f.append(f"domains: [{', '.join(DOMAIN_OVERRIDE.get(it['id'], DOMAINS[prefix]))}]")
        if not tagged:
            # 층위를 문서에서 읽지 않고 기본값으로 채웠다는 표시.
            # 태깅을 마치면 이 필드가 사라진다
            f.append("level_verified: false")
        if it["id"] in DEFERS:
            f.append(f"defers_to: [{', '.join(DEFERS[it['id']])}]")
        f.append(f"title: {quote(it['title'])}")
        if it["criteria"]:
            f.append(f"criteria: {quote(it['criteria'])}")
        out.append("  - {" + ", ".join(f) + "}")

    return "\n".join(out) + "\n", len(items)


def prefix_of(item_id):
    return item_id.rsplit("-", 2)[0]


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("root")
    ap.add_argument("pattern")
    ap.add_argument("source", choices=sorted(CI_STAGE))
    ap.add_argument("default_level", nargs="?", default=None)
    ap.add_argument("-o", "--out", help="쓰지 않으면 표준 출력으로 낸다")
    ap.add_argument("--check", action="store_true",
                    help="파일을 쓰지 않고 기존 것과 같은지만 본다")
    args = ap.parse_args()

    text, n = build(args.root, args.pattern, args.source, args.default_level)

    if args.check:
        if not args.out:
            sys.exit("--check 에는 -o 로 비교 대상을 줘야 한다")
        old = Path(args.out).read_text(encoding="utf-8")
        if old == text:
            print(f"OK  {args.source} {n}건. 문서와 레지스트리가 일치한다")
            return 0
        diff = difflib.unified_diff(old.splitlines(), text.splitlines(),
                                    "기존", "문서에서 생성", lineterm="")
        print("\n".join(list(diff)[:40]))
        print(f"\n어긋난다. gen_items.py 를 -o 로 다시 돌려라")
        return 1

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{args.source} {n}건 -> {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
