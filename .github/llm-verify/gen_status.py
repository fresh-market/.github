#!/usr/bin/env python3
"""
검증 현황 문서 생성기.

"지금 무엇을 검증하고 있는가" 를 레지스트리와 앵커 규칙에서 계산해 문서로 낸다.

손으로 쓰면 항목이 늘거나 규칙이 바뀔 때마다 조용히 어긋난다.
이 문서의 숫자는 전부 파생값이므로 사람이 고치지 않는다.

    python3 gen_status.py --backend <경로> --common <경로> --infra <경로> -o <출력 파일>

    python3 gen_status.py --backend ../../../fm-backend \\
                          --common  ../../../.github \\
                          --infra   ../../../fm-infra \\
                          -o ../../../fm-backend/docs/verification/verification-status.md

    이 스크립트는 common 저장소의 .github/llm-verify/ 에 있다. 세 단계 위가 저장소들의 부모다.

저장소 이름이 바뀌어도 동작하도록 경로를 각각 받는다.
디렉터리 이름을 가정하면 클론 이름이 다른 사람에게서 조용히 실패한다. run.py 와 같은 방식이다.
"""

import argparse
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import active_items, items_of, load_yaml, match_rules  # noqa: E402

REPOS = ["common", "backend", "infra"]


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "?"


def main():
    ap = argparse.ArgumentParser()
    for r in REPOS:
        ap.add_argument(f"--{r}", required=True, help=f"{r} 저장소 경로")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    # 저장소 이름이 아니라 갈래 이름을 키로 쓴다. 경로는 인자가 정한다
    R = {r: Path(getattr(args, r)).resolve() for r in REPOS}

    regs = {r: items_of(R[r] / ".github/llm-verify/items.yml") for r in REPOS}
    anchors = load_yaml(R["backend"] / ".github/llm-verify/anchors.yml")
    conflicts = load_yaml(R["common"] / ".github/llm-verify/known-conflicts.yml")
    # active_items 가 붙여 주는 repo 를 원본에도 달아 둔다
    allit = [dict(i, repo=r) for r, v in regs.items() for i in v]
    byid = {i["id"]: i for i in allit}

    # 규칙별 활성 항목
    per_rule = {}
    for rule in anchors["rules"]:
        act = active_items([rule], regs)
        per_rule[rule["id"]] = act
    fb = dict(anchors["defaults"]["on_no_match"])
    fb["id"] = "on_no_match"
    per_rule["(어떤 규칙도 안 걸림)"] = active_items([fb], regs)

    reach = set()
    for rid, act in per_rule.items():
        if rid != "(어떤 규칙도 안 걸림)":
            reach |= set(act)
    unreach = [i for i in allit if i["id"] not in reach]

    # 판정 대상이 있는가
    java = list(R["backend"].glob("src/**/*.java"))
    have = {
        "backend 의 Java 코드": (len(java) > 0, f"{len(java)}개"),
        "backend/build.gradle": ((R["backend"] / "build.gradle").is_file(), ""),
        "backend 앵커 규칙": ((R["backend"] / ".github/llm-verify/anchors.yml").is_file(),
                          f"규칙 {len(anchors['rules'])}개"),
        "infra 앵커 규칙": ((R["infra"] / ".github/llm-verify/anchors.yml").is_file(), ""),
        "G-PR 호출자 워크플로": ((R["backend"] / ".github/workflows/llm-verify.yml").is_file(), ""),
        "G-PR 본체 워크플로": ((R["common"] / ".github/workflows/llm-verify.yml").is_file(), ""),
        "G-LOCAL 절차": ((R["backend"] / ".claude/commands/verify.md").is_file(), ""),
        "레지스트리 검사 워크플로": (
            all((R[r] / ".github/workflows/registry-check.yml").is_file() for r in REPOS),
            "3개 저장소"),
    }

    L = []
    w = L.append
    w("# 검증 현황")
    w("")
    w("**이 문서는 `gen_status.py` 가 만든다. 손으로 고치지 않는다.**")
    w("레지스트리와 앵커 규칙에서 계산한 값이라, 항목이나 규칙이 바뀌면 다시 생성해야 한다.")
    w("")
    w(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    w("")
    w("| 저장소 | 커밋 | 항목 |")
    w("|---|---|---:|")
    for r in REPOS:
        w(f"| `{r}` | `{git(R[r], 'rev-parse', '--short', 'HEAD')}` | {len(regs[r])} |")
    w(f"| | | **{len(allit)}** |")
    w("")

    # --- 게이트별 상태 ---
    w("## 게이트가 지금 도는가")
    w("")
    w("| 게이트 | 판정 주체 | 차단 | 상태 |")
    w("|---|---|---|---|")
    ok_build = have["backend/build.gradle"][0]
    ok_code = have["backend 의 Java 코드"][0]
    w(f"| G-LOCAL | Claude, 로컬 | 안 함 | "
      f"{'돈다' if have['G-LOCAL 절차'][0] else '**절차 없음**'}"
      f"{'' if ok_code else '. 판정 대상 코드가 없어 기본 집합만 켜진다'} |")
    w(f"| G-BUILD | Gradle, SonarQube | **함** | "
      f"{'돈다' if ok_build else '**build.gradle 이 없어 돌지 않는다**'} |")
    w(f"| G-PR | gemini-2.5-flash | 안 함 | "
      f"{'워크플로 있음' if have['G-PR 호출자 워크플로'][0] else '**워크플로 없음**'}. "
      f"`GEMINI_API_KEY` 등록 여부는 로컬에서 확인할 수 없다 |")
    w("| G-RELEASE | 배포 스크립트 | **함** | **스크립트 없음** |")
    w("| G-AUDIT | 주기 작업 | 안 함 | **없음** |")
    w(f"| 레지스트리 검사 | `gen_items.py --check` | **함** | "
      f"{'돈다' if have['레지스트리 검사 워크플로'][0] else '**워크플로 없음**'} |")
    w("")

    # --- 준비 상태 ---
    w("### 있는 것과 없는 것")
    w("")
    w("```")
    for name, (ok, note) in have.items():
        mark = "있음" if ok else "없음"
        w(f"  {mark}  {name}" + (f"  ({note})" if note and ok else ""))
    w("```")
    w("")

    # --- 무엇이 켜지나 ---
    w("## 바꾼 파일별로 켜지는 항목")
    w("")
    w("| 트리거 | 규칙 | 활성 | 1단계 | 2단계 | backend | common | infra |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for rule in anchors["rules"]:
        act = per_rule[rule["id"]]
        c = Counter(i["repo"] for i in act.values())
        s = Counter(i["ci_stage"] for i in act.values())
        trig = ", ".join(f"`{t}`" for t in rule["trigger"])
        w(f"| {trig} | {rule['id']} | {len(act)} | {s[1]} | {s[2]} | "
          f"{c['backend']} | {c['common']} | {c['infra']} |")
    act = per_rule["(어떤 규칙도 안 걸림)"]
    w(f"| (해당 없음) | 기본 집합 | {len(act)} | {len(act)} | 0 | {len(act)} | 0 | 0 |")
    w("")
    w("여러 파일을 바꾸면 합집합이다.")
    w("")

    # --- 분포 ---
    w("## 항목 분포")
    w("")
    w("| 층위 | 건수 | 게이트 | 건수 |")
    w("|---|---:|---|---:|")
    lv = Counter(i["level"] for i in allit)
    gt = Counter(i["gate"] for i in allit)
    rows = max(len(lv), len(gt))
    lvl = sorted(lv.items(), key=lambda x: -x[1])
    gtl = sorted(gt.items(), key=lambda x: -x[1])
    for n in range(rows):
        a = f"`[{lvl[n][0]}]` | {lvl[n][1]}" if n < len(lvl) else " | "
        b = f"`{gtl[n][0]}` | {gtl[n][1]}" if n < len(gtl) else " | "
        w(f"| {a} | {b} |")
    w("")

    # --- 미도달 ---
    w("## PR 로 판정되지 않는 항목")
    w("")
    w(f"{len(allit)}건 중 **{len(reach)}건**이 어떤 규칙엔가 걸린다. "
      f"나머지 {len(unreach)}건은 아래와 같다.")
    w("")
    w("| 게이트 | 건수 | 접두사 |")
    w("|---|---:|---|")
    byg = defaultdict(list)
    for i in unreach:
        byg[i["gate"]].append(i["id"].rsplit("-", 2)[0])
    for g, ps in sorted(byg.items(), key=lambda x: -len(x[1])):
        c = Counter(ps)
        w(f"| `{g}` | {len(ps)} | {', '.join(f'{k} {v}' for k, v in c.most_common())} |")
    w("")
    audit = sum(len(v) for g, v in byg.items() if g in ("G-AUDIT", "G-RELEASE"))
    hole = [i for i in unreach if i["gate"] in ("G-PR", "G-DESIGN")]
    w(f"`G-AUDIT` 과 `G-RELEASE` {audit}건은 **빠진 것이 아니라 다른 게이트 소관이다.** "
      "기록을 봐야 하거나 런타임 조회가 필요해 PR 단위로 판정할 수 없다.")
    w("")
    if hole:
        w(f"**`G-PR` 과 `G-DESIGN` {len(hole)}건은 다르다.** "
          "PR 에서 판정해야 하는데 어떤 앵커 규칙도 켜지 않는다. 실제로 열려 있는 구멍이다.")
        w("")
        w("| 항목 | 층위 | 제목 |")
        w("|---|---|---|")
        for i in sorted(hole, key=lambda x: x["id"]):
            w(f"| `{i['id']}` | {i['level']} | {i['title']} |")
        w("")
        w("메우려면 이 항목들을 켜는 앵커 규칙을 만들거나, 층위를 고쳐 다른 게이트로 보낸다.")
        w("")

    # --- 판정을 막고 있는 것 ---
    w("## 판정을 막고 있는 것")
    w("")
    unres = [c for c in conflicts.get("conflicts", []) if c.get("status") == "unresolved"]
    inten = [c for c in conflicts.get("conflicts", []) if c.get("status") == "intentional"]
    affected = sorted({a for c in unres for a in c.get("affects", []) if a in byid})
    w(f"### 확정값 모순 {len(unres)}건")
    w("")
    w("문서마다 다르게 적혀 있어 `CONFLICTING_BASELINE` 으로 유보된다. "
      "한쪽을 골라 판정하면 LLM 이 팀의 결정을 대신 내리는 것이 된다.")
    w("")
    w("| 주제 | 유보되는 항목 |")
    w("|---|---|")
    for c in unres:
        ids = [a for a in c.get("affects", []) if a in byid]
        w(f"| {c['topic']} | {', '.join(f'`{i}`' for i in ids) or '-'} |")
    w("")
    w(f"영향받는 항목은 중복 제외 **{len(affected)}건**이다. "
      f"결정하는 법은 `infra/docs/infra-review/pending-decisions.md` 에 있다.")
    w("")
    if inten:
        shadow = [c for c in inten
                  if any(a in affected for a in c.get("affects", []))]
        w(f"### 의도된 이탈 {len(inten)}건")
        w("")
        w("모순이 아니라 이 팀이 일반론에서 의도적으로 벗어난 것이다. 확정값 쪽으로 판정한다.")
        if shadow:
            w("")
            w(f"이 중 **{len(shadow)}건은 위 모순에 가려 동작하지 않는다.** "
              "확정값끼리 어긋나 있으면 확정값을 기준으로 판정하라는 지시가 성립하지 않는다.")
        w("")
    nv = [i for i in allit if i.get("level_verified") is False]
    if nv:
        c = Counter(i["repo"] for i in nv)
        w(f"### 층위 미검증 {len(nv)}건")
        w("")
        detail = ", ".join(f"{k} {v}건" for k, v in sorted(c.items()))
        w(f"{detail} 의 층위 태그가 기본값으로 채워져 있다. "
          "실제와 다른 것이 섞여 있어 `levels` 필터가 정확하지 않다.")
        w("")

    w("## 다시 생성하는 법")
    w("")
    w("```bash")
    w("python3 common/.github/llm-verify/gen_status.py . \\")
    w("        -o backend/docs/verification/verification-status.md")
    w("```")
    w("")
    w("항목을 추가하거나 앵커 규칙을 고친 뒤에 돌린다.")

    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"  {args.out}  ({len(L)}줄, 항목 {len(allit)}건)")


if __name__ == "__main__":
    main()
