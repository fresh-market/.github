#!/usr/bin/env python3
"""
G-PR 실행기.

fresh-market/fm-backend 의 docs/verification/verification-workflow.md "진입점부터의 실행 순서" 4~16 단계를 수행한다.
워크플로 yml 은 체크아웃과 코멘트만 하고, 판정 파이프라인은 전부 여기 있다.

두 모드로 나뉜다.
  match  앵커 규칙만 매칭해 needs_baseline 을 내놓는다. infra 체크아웃 여부를 정하기 위해서다
  judge  4~16 단계 전체

설계 문서와 다른 점이 하나 있다.
13단계(기준선 판정)는 base 커밋에 같은 판정을 돌려 신규 위반과 기존 부채를 가르도록 되어 있으나,
여기서는 LLM 호출을 두 배로 늘리지 않기 위해 다르게 구현했다.
판정 근거의 파일과 줄 번호가 이 PR 이 추가한 줄에 있는지를 diff 로 대조한다.
결정론적이고 호출이 늘지 않는 대신, 추가된 줄 밖에 근거가 있는 신규 위반(예: 줄을 지워서 생긴 위반)은
기존 부채로 분류된다. 그 한계를 알고 쓴다.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import yaml

MODEL = "gemini-2.5-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

# 사고 토큰이 maxOutputTokens 예산에서 나간다.
# 묶지 않으면 동적으로 배정되는데, 11만 토큰짜리 프롬프트로 200건을 판정하는 동안
# 예산을 다 써서 정작 답을 쓸 자리가 남지 않고 finishReason=MAX_TOKENS 로 끝난다.
# 그러면 항목 전부가 UNJUDGED 가 되므로 게이트가 없는 것과 같다.
# 8192 를 남기면 출력에 57344 가 남아 300건대를 쓰기에 넉넉하다.
THINKING_BUDGET = 8192

# CI 가 판정하는 단계. 1단계가 backend, 2단계가 common + infra 다.
#
# CI 는 1단계만 본다. 2단계는 G-LOCAL 이 맡는다.
# 2단계를 넣으면 호출이 배로 늘어 무료 티어 분당 10회를 한 PR 이 다 쓰고,
# 정작 판정 대상 코드는 backend 뿐이라 얻는 것에 비해 비용이 크다.
# 되돌리려면 (1, 2) 로 바꾸면 된다. 항목의 ci_stage 는 그대로 두었다.
CI_STAGES = (1,)

# 한 호출에 넣는 항목 수. 예산을 묶어도 한 번에 200건을 요구하면 출력이 여전히 크다.
# 나눠 부르면 호출당 출력이 그만큼 줄어 MAX_TOKENS 를 넘길 일이 없다.
# 무료 티어가 분당 10회라 50 이면 300건대에서 7회 안팎으로 한도 안에 들어온다.
# 한 덩어리가 실패해도 나머지 판정은 살아남는다.
CHUNK = 50

VERDICTS = ["VIOLATION", "OK", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE", "CONFLICTING_BASELINE"]


# --- 유틸 ---------------------------------------------------------------

def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r.stdout


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def items_of(path):
    d = load_yaml(path)
    return d["items"] if isinstance(d, dict) else d


def glob_re(pattern):
    """`**/` 를 임의 깊이로, `*` 를 한 경로 조각 안으로 해석한다."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path, patterns):
    return any(glob_re(p).match(path) for p in patterns)


def prefix_of(item_id):
    return item_id.rsplit("-", 2)[0]


# --- 4단계: 범위 산출 -----------------------------------------------------

def changed_files(repo, base, head):
    out = git(repo, "diff", "--name-only", f"{base}...{head}")
    return [l for l in out.splitlines() if l.strip()]


def unified_diff(repo, base, head):
    return git(repo, "diff", "--unified=3", f"{base}...{head}")


def added_lines(diff_text):
    """파일별로 이 PR 이 추가한 줄 번호 집합. 13단계 대체 구현이 쓴다."""
    result = defaultdict(set)
    path, lineno = None, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif path and line.startswith("+") and not line.startswith("+++"):
            result[path].add(lineno)
            lineno += 1
        elif path and not line.startswith("-"):
            lineno += 1
    return result


# --- 5, 6단계: 앵커 규칙 매칭 ----------------------------------------------

def match_rules(anchors, files):
    matched = [r for r in anchors["rules"] if matches_any(files, r["trigger"])]
    if matched:
        return matched, False
    fallback = dict(anchors["defaults"]["on_no_match"])
    fallback.setdefault("id", "on_no_match")
    fallback.setdefault("anchors", [])
    fallback["needs_baseline_values"] = False
    return [fallback], True


def matches_any(files, patterns):
    return any(matches(f, patterns) for f in files)


# --- 7, 8단계: 레지스트리 로드와 필터 ---------------------------------------

def active_items(rules, registries):
    """활성 조건을 만족하는 항목. 여러 규칙에 걸리면 합집합이다."""
    active = {}
    for rule in rules:
        a = rule.get("activate") or {}
        prefixes = set(a.get("prefixes") or [])
        levels = set(a.get("levels") or [])
        chapters = a.get("chapters") or {}
        for repo, items in registries.items():
            for it in items:
                p = prefix_of(it["id"])
                if p not in prefixes:
                    continue
                if levels and it.get("level") not in levels:
                    continue
                if p in chapters and it.get("ch") not in chapters[p]:
                    continue
                active.setdefault(it["id"], dict(it, repo=repo))
    return active


# --- 9~12단계: 입력 수집 ---------------------------------------------------

def read_files(root, patterns, limit_bytes=400_000):
    """
    앵커 파일을 읽는다. 결과를 셋으로 나눈다.

    got     읽은 파일
    absent  패턴에 해당하는 파일이 아예 없다. 이것은 실패가 아니라 부재 판정의 근거다
    failed  있는데 못 읽었다. 이쪽이 INSUFFICIENT_EVIDENCE 사유다

    둘을 구분하지 않으면 "SecurityConfig 가 없다" 는 판정이 "증거 부족" 으로 뭉개진다.
    점검 항목의 대부분이 무언가의 부재를 묻기 때문에 이 구분이 게이트의 실효를 좌우한다.
    """
    root = Path(root)
    got, absent, failed, total = {}, [], [], 0
    for pattern in patterns:
        hits = [f for f in sorted(root.glob(pattern)) if f.is_file()]
        if not hits:
            absent.append(pattern)
            continue
        for f in hits:
            rel = str(f.relative_to(root))
            if rel in got:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                failed.append(f"{rel} ({e})")
                continue
            if total + len(text) > limit_bytes:
                failed.append(f"{rel} (용량 상한 초과)")
                continue
            got[rel] = text
            total += len(text)
    return got, absent, failed


def collect_docs(active, roots):
    """활성 항목이 속한 판정 기준 문서만 읽는다."""
    doc_dirs = {
        "common": Path(roots["common"]) / "docs" / "software-quality",
        "backend": Path(roots["backend"]) / "docs" / "code-architecture",
        "infra": Path(roots["infra"] or ".") / "docs" / "infra-review",
    }
    wanted = defaultdict(set)
    for it in active.values():
        wanted[it["repo"]].add(it["doc"])
    docs, missing = {}, []
    for repo, names in wanted.items():
        for name in sorted(names):
            path = doc_dirs[repo] / name
            if path.is_file():
                docs[f"{repo}/{name}"] = path.read_text(encoding="utf-8", errors="replace")
            else:
                missing.append(f"{repo}/{name}")
    return docs, missing


def collect_baseline(infra_root, limit_bytes=400_000):
    """
    확정값 문서를 읽는다. 앵커 규칙이 needs_baseline_values 를 걸었을 때만 부른다.

    이 문서들은 "왜 그 값인가" 를 담고 있어 크다(전체 165KB). 매번 넣으면 토큰이 낭비되고,
    무엇보다 판정과 무관한 서술이 많아 LLM 의 주의를 흩뜨린다.
    타임아웃 값이나 풀 크기를 확정값과 대조해야 하는 규칙에서만 넣는다.
    """
    if not infra_root:
        return {}, ["infra 저장소가 없다"]
    root = Path(infra_root) / "docs" / "system-design"
    if not root.is_dir():
        return {}, [f"{root} 가 없다"]
    got, failed, total = {}, [], 0
    for f in sorted(root.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if total + len(text) > limit_bytes:
            failed.append(f"{f.name} (용량 상한 초과)")
            continue
        got[f.name] = text
        total += len(text)
    return got, failed


def conflict_map(path):
    """
    항목 ID -> 모순 정보. 두 종류를 나눠 돌려준다.

    unresolved   문서끼리 어긋난다. 판정을 유보시킨다
    intentional  모순이 아니다. 이 팀이 일반론에서 의도적으로 벗어난 것이다

    뒤엣것을 알려 주지 않으면 LLM 이 일반론만 보고 위반이라고 답한다.
    확정값 문서에 이유와 ADR 번호까지 있는 결정을 매 PR 마다 되짚게 된다.
    """
    if not Path(path).is_file():
        return {}, {}
    data = load_yaml(path)
    unresolved, intentional = defaultdict(list), defaultdict(list)
    for c in data.get("conflicts", []):
        target = {"unresolved": unresolved, "intentional": intentional}.get(c.get("status"))
        if target is None:
            continue
        for item_id in c.get("affects", []):
            target[item_id].append(c)
    return unresolved, intentional


# --- 14, 15단계: LLM 호출 --------------------------------------------------

SYSTEM = """너는 웹 백엔드 코드 리뷰어다. 주어진 점검 항목 하나하나에 대해 판정한다.

규칙
1. 요청받은 모든 항목 ID 에 대해 정확히 하나씩 답한다. 빼거나 더하지 않는다.
2. 근거 없이 OK 를 내지 않는다. 판정에 필요한 파일을 못 봤으면 INSUFFICIENT_EVIDENCE 다.
3. 변경과 무관한 항목은 NOT_APPLICABLE 이다. 무리해서 위반을 만들지 않는다.
4. VIOLATION 은 file 과 line 을 반드시 채운다. 못 채우면 INSUFFICIENT_EVIDENCE 다.
5. 판정 기준은 첨부한 문서 본문이다. 항목 제목만 보고 일반론으로 판정하지 않는다.
6. CONFLICTING_BASELINE 으로 표시된 항목은 그대로 CONFLICTING_BASELINE 으로 답하고 양쪽 값을 적는다.
6-1. "의도된 이탈" 로 표시된 항목은 모순이 아니다. 함께 적힌 결정을 기준으로 판정한다.
   점검 항목 본문의 일반론과 다르다는 이유로 위반이라고 답하지 않는다.
7. 앵커 파일은 diff 에 없어도 첨부된 것이다. "저장소에 존재하지 않는 경로" 목록은
   검색 실패가 아니라 부재의 확인이므로, 무언가가 없다는 판정의 근거로 그대로 쓴다.
8. reason 과 fix 는 한국어로 각각 한 문장씩 쓴다.
   다만 항목 ID, verdict, 파일 경로, 클래스명, 메서드명, 설정 키와 값은 원문 그대로 둔다.
   번역하면 검색과 대조가 깨진다.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "reason": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["id", "verdict"],
            },
        }
    },
    "required": ["results"],
}


def build_prompt(items, diff, anchor_files, absent, docs, conflicts,
                 intentional=None, baseline=None):
    intentional = intentional or {}
    parts = ["# 판정할 점검 항목\n"]
    for it in items:
        mark = ""
        if it["id"] in conflicts:
            vals = "; ".join(
                f"{s['doc']} {s.get('section','')}: {s['value']}"
                for c in conflicts[it["id"]] for s in c["sources"]
            )
            mark = f"  [확정값 모순 - CONFLICTING_BASELINE 으로 답할 것] {vals}"
        elif it["id"] in intentional:
            # unresolved 가 먼저다. 확정값 쪽이 자기들끼리 어긋나 있으면
            # "확정값을 기준으로 판정하라" 는 지시 자체가 성립하지 않는다.
            # 일반론과 다른 것이 위반이 아니라 결정인 경우이므로,
            # 확정값 쪽을 기준으로 판정하게 하고 근거와 결정 번호를 함께 준다
            c = intentional[it["id"]][0]
            decided = c["sources"][-1]
            mark = ("  [의도된 이탈 - 아래 결정을 기준으로 판정할 것. "
                    f"이 항목의 일반론을 근거로 위반이라고 답하지 말 것] "
                    f"{decided['doc']} {decided.get('section', '')}: {decided['value']}")
            if c.get("decision"):
                mark += f" (결정 {c['decision']}, 되돌릴 수 없음)"
        parts.append(f"- {it['id']} ({it['level']}) {it['title']}{mark}")

    parts.append("\n# 변경 내용 (판정 대상)\n```diff\n" + diff + "\n```")

    parts.append("\n# 앵커 파일 (diff 에 없어도 첨부된 것. 부재 판정의 근거)\n")
    for path, text in anchor_files.items():
        parts.append(f"## {path}\n```\n{text}\n```")

    if absent:
        parts.append(
            "\n# 저장소에 존재하지 않는 경로\n"
            "아래 패턴에 해당하는 파일은 저장소 전체를 뒤져도 없다. 검색 실패가 아니라 부재다.\n"
            "이 사실을 무언가가 없다는 판정의 근거로 쓴다. 증거 부족으로 처리하지 않는다.\n"
        )
        for p in absent:
            parts.append(f"- `{p}` 없음")

    parts.append("\n# 판정 기준 본문\n")
    for name, text in docs.items():
        parts.append(f"## {name}\n{text}")

    if baseline:
        parts.append(
            "\n# 확정값\n"
            "이 팀이 실제로 정한 값이다. 점검 항목 본문의 일반론과 어긋나면 **확정값이 이긴다.**\n"
            "근거가 더 구체적이기 때문이다. 값을 대조하는 항목은 여기 적힌 수치를 기준으로 판정한다.\n"
        )
        for name, text in baseline.items():
            parts.append(f"## {name}\n{text}")

    return "\n".join(parts)


def call_gemini(api_key, prompt, expected_ids, attempts=3):
    """
    일시적 실패에 재시도한다.

    무료 티어는 RPM 10 이고 503 이 드물지 않다. 재시도가 없으면 한 번의 일시 실패로
    1단계가 죽고 464건 전부가 UNJUDGED 가 된다. 그건 게이트가 없는 것과 같다.
    응답이 왔는데 형식이 어긋난 경우는 재시도하지 않는다. 다시 불러도 같기 때문이다.
    """
    last = None
    for n in range(attempts):
        result, err = _call_once(api_key, prompt, expected_ids)
        if result is not None:
            return result, None
        last = err
        if not _retryable(err) or n == attempts - 1:
            return None, last
        wait = 2 ** n * 5          # 5초, 10초
        print(f"  재시도 {n + 1}/{attempts - 1} ({err}). {wait}초 대기", file=sys.stderr)
        time.sleep(wait)
    return None, last


def _retryable(err):
    """429(한도)와 5xx(서버)만 다시 부른다. 400 이나 파싱 실패는 다시 불러도 같다."""
    return any(s in err for s in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503",
                                 "HTTP 504", "호출 실패"))


def _call_once(api_key, prompt, expected_ids):
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "maxOutputTokens": 65536,
            "thinkingConfig": {"thinkingBudget": THINKING_BUDGET},
        },
    }
    req = urllib.request.Request(
        ENDPOINT.format(MODEL) + f"?key={api_key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return None, f"호출 실패: {e}"

    cand = (data.get("candidates") or [{}])[0]
    finish = cand.get("finishReason")
    if finish not in (None, "STOP"):
        return None, f"finishReason={finish}"

    try:
        text = cand["content"]["parts"][0]["text"]
        results = json.loads(text)["results"]
    except Exception as e:
        return None, f"파싱 실패: {e}"

    usage = data.get("usageMetadata", {})
    seen = {r["id"] for r in results}
    ok = seen == set(expected_ids)
    detail = "" if ok else f"응답 {len(seen)} / 요청 {len(expected_ids)}"
    return {"results": results, "usage": usage, "complete": ok, "detail": detail}, None


# --- 16단계: 필터링과 출력 -------------------------------------------------

def suppress_deferred(results, active):
    """defers_to 대상이 위반이면 일반 항목은 발화하지 않는다."""
    violating = {r["id"] for r in results if r["verdict"] == "VIOLATION"}
    kept, suppressed = [], []
    for r in results:
        target = active.get(r["id"], {}).get("defers_to") or []
        if r["verdict"] == "VIOLATION" and any(t in violating for t in target):
            suppressed.append(r)
        else:
            kept.append(r)
    return kept, suppressed


def split_new(results, added):
    """13단계 대체 구현. 근거 줄이 추가된 줄이면 이 PR 이 만든 것으로 본다."""
    new, existing = [], []
    for r in results:
        f, ln = r.get("file"), r.get("line")
        if f and ln and ln in added.get(f, set()):
            new.append(r)
        else:
            existing.append(r)
    return new, existing


def origin(it):
    """항목이 어느 저장소 어느 문서 몇 장에서 왔는지. 지적만 받고 기준 본문을 못 찾는 일을 막는다."""
    doc = it.get("doc")
    if not doc:
        return ""
    ch = it.get("ch")
    return f"{it.get('repo','?')} `{doc}`" + (f" {ch}장" if ch else "")


def render(ctx):
    L = ["<!-- llm-verify -->", "## LLM 검증 (G-PR)", ""]
    L.append(f"매칭된 규칙 `{'`, `'.join(ctx['rules'])}`" + ("  (기본 규칙)" if ctx["fallback"] else ""))
    L.append(f"활성 항목 **{ctx['active_n']}건**  "
             f"(backend {ctx['by_repo']['backend']}, common {ctx['by_repo']['common']}, infra {ctx['by_repo']['infra']})")
    if ctx.get("deferred"):
        L.append(f"G-LOCAL 담당 {len(ctx['deferred'])}건은 여기서 보지 않는다 (common, infra 항목)")
    L.append("")

    for stage, info in ctx["stages"].items():
        n_chunk = info.get("chunks")
        tail = f" ({n_chunk}회 나눠 호출)" if n_chunk and n_chunk > 1 else ""
        if info["error"]:
            L.append(f"- {stage}단계 **실패**: {info['error']}  -> 해당 항목 `UNJUDGED`{tail}")
        elif not info["complete"]:
            L.append(f"- {stage}단계 부분 응답: {info['detail']}  -> 누락분 `UNJUDGED`{tail}")
        else:
            L.append(f"- {stage}단계 완료 {info['n']}건{tail}")
    L.append("")

    if ctx["new"]:
        L.append(f"### 이 PR 이 만든 위반 {len(ctx['new'])}건")
        L.append("")
        for r in ctx["new"]:
            it = ctx["active"][r["id"]]
            L.append(f"**`{r['id']}`** {it['title']}")
            L.append(f"- 기준: {origin(it)}")
            L.append(f"- `{r.get('file')}:{r.get('line')}`")
            L.append(f"- {r.get('reason','')}")
            if r.get("fix"):
                L.append(f"- 고치기: {r['fix']}")
            L.append("")
    elif ctx["unjudged"]:
        # 판정이 안 된 것과 위반이 없는 것은 다르다.
        # 전부 미판정인데 "위반 없음" 을 상단에 내면 게이트가 통과한 것으로 읽힌다.
        L.append(f"### 판정하지 못했다. 미판정 {len(ctx['unjudged'])}건")
        L.append("")
        L.append("**위반이 없다는 뜻이 아니다.** 아래 상자에 미판정 목록이 있다.")
        L.append("")
    else:
        L.append("### 이 PR 이 만든 위반 없음")
        L.append("")

    if ctx["existing"]:
        L.append("<details><summary>기존 부채 " + str(len(ctx["existing"])) + "건</summary>")
        L.append("")
        for r in ctx["existing"]:
            it = ctx["active"][r["id"]]
            L.append(f"- `{r['id']}` {it['title']}  `{r.get('file') or '-'}`  ({origin(it)})")
        L.append("")
        L.append("</details>")
        L.append("")

    if ctx["conflicting"]:
        L.append("<details><summary>확정값 모순으로 유보 " + str(len(ctx["conflicting"])) + "건</summary>")
        L.append("")
        for r in ctx["conflicting"]:
            L.append(f"- `{r['id']}` {r.get('reason','')}  ({origin(ctx['active'][r['id']])})")
        L.append("")
        L.append("</details>")
        L.append("")

    # 집계 숫자만 내면 어느 항목이 판정되지 않았는지 알 수 없어,
    # "앵커 규칙을 보강하라" 는 조치를 실행할 수 없다
    if ctx["insufficient"]:
        L.append("<details><summary>증거 부족으로 판정 못함 "
                 + str(len(ctx["insufficient"])) + "건</summary>")
        L.append("")
        for r in ctx["insufficient"]:
            it = ctx["active"][r["id"]]
            L.append(f"- `{r['id']}` {it['title']}  ({origin(it)})")
            if r.get("reason"):
                L.append(f"  - {r['reason']}")
        L.append("")
        L.append("같은 항목이 매번 여기 나오면 판정이 어려운 코드가 아니라 "
                 "`anchors.yml` 의 앵커 목록이 부족한 것이다.")
        L.append("")
        L.append("</details>")
        L.append("")

    if ctx["unjudged"]:
        L.append("<details><summary>미판정 " + str(len(ctx["unjudged"])) + "건</summary>")
        L.append("")
        L.append("**통과가 아니다.** 물어보지 않았거나 응답이 오지 않은 항목이다. "
                 "로컬에서 `./verify.sh` 를 돌리면 전부 판정된다.")
        L.append("")
        for i in ctx["unjudged"][:60]:
            L.append(f"- `{i}` {ctx['active'][i]['title']}")
        if len(ctx["unjudged"]) > 60:
            L.append(f"- 외 {len(ctx['unjudged']) - 60}건")
        L.append("")
        L.append("</details>")
        L.append("")

    counts = ctx["counts"]
    L.append("| verdict | 건수 |")
    L.append("|---|---:|")
    for v in VERDICTS + ["UNJUDGED"]:
        L.append(f"| `{v}` | {counts.get(v, 0)} |")
    L.append("")

    if ctx["absent"]:
        L.append("저장소에 없는 앵커 경로 " + str(len(ctx["absent"]))
                 + "건 (부재 판정의 근거로 썼다): "
                 + ", ".join(f"`{p}`" for p in ctx["absent"][:8]))
        L.append("")
    if ctx["missing_anchors"]:
        L.append("**읽지 못한 앵커** " + ", ".join(f"`{m}`" for m in ctx["missing_anchors"][:10])
                 + "  -> 이것에 의존한 항목은 `INSUFFICIENT_EVIDENCE` 다")
        L.append("")
    if ctx["suppressed"]:
        L.append(f"`defers_to` 로 억제된 중복 지적 {len(ctx['suppressed'])}건")
        L.append("")

    L.append("---")
    L.append("이 게이트는 **병합을 막지 않는다.** 재현율이 측정되지 않았기 때문이다. "
             "차단은 G-BUILD(커버리지, Blocker)와 G-RELEASE 가 한다.")
    return "\n".join(L)


# --- 진입점 ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["match", "judge"], required=True)
    ap.add_argument("--backend", required=True)
    ap.add_argument("--common")
    ap.add_argument("--infra", default="")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", default="verify-out.md")
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM 을 부르지 않고 무엇이 활성화되어 어떤 입력이 만들어지는지만 본다")
    args = ap.parse_args()

    anchors = load_yaml(Path(args.backend) / ".github/llm-verify/anchors.yml")
    files = changed_files(args.backend, args.base, args.head)
    rules, fallback = match_rules(anchors, files)
    needs_baseline = any(r.get("needs_baseline_values") for r in rules)

    if args.mode == "match":
        out = os.environ.get("GITHUB_OUTPUT")
        # 확정값 문서는 29만 자라 판정 입력에서 가장 크다. 규칙이 걸렸다는 이유만으로
        # 통째로 읽으면 그것만으로 컨텍스트가 찬다. 값을 대조하는 항목은 REL 과 INF 뿐이므로
        # 그것이 실제로 활성일 때만 읽으라고 알려준다.
        registries = {r: items_of(Path(p) / ".github/llm-verify/items.yml")
                      for r, p in (("backend", args.backend), ("common", args.common),
                                   ("infra", args.infra))}
        active = active_items(rules, registries)
        baseline_ids = sorted(i for i in active
                              if i.startswith("REL-") or i.startswith("INF-"))
        s1 = [i for i, it in active.items() if it.get("ci_stage", 1) == 1]
        payload = {
            "needs_baseline": "true" if needs_baseline and baseline_ids else "false",
            "baseline_items": str(len(baseline_ids)),
            "active": str(len(active)),
            "stage1": str(len(s1)),
            "stage2": str(len(active) - len(s1)),
            "rules": ",".join(r["id"] for r in rules),
            "changed": str(len(files)),
        }
        if out:
            with open(out, "a") as f:
                for k, v in payload.items():
                    f.write(f"{k}={v}\n")
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    roots = {"backend": args.backend, "common": args.common, "infra": args.infra}
    registries = {
        "backend": items_of(Path(args.backend) / ".github/llm-verify/items.yml"),
        "common": items_of(Path(args.common) / ".github/llm-verify/items.yml"),
    }
    if args.infra:
        registries["infra"] = items_of(Path(args.infra) / ".github/llm-verify/items.yml")

    active = active_items(rules, registries)

    # CI 가 보지 않는 단계의 항목은 활성에서 뺀다.
    # 남겨 두면 판정하지 않은 것이 UNJUDGED 로 쌓여, 담당이 아니어서 안 본 것과
    # 물었는데 답이 안 온 것이 뒤섞인다. 그 둘은 조치가 다르다.
    deferred_to_local = {i: it for i, it in active.items()
                         if it.get("ci_stage", 1) not in CI_STAGES}
    active = {i: it for i, it in active.items() if i not in deferred_to_local}

    if not active:
        Path(args.out).write_text("<!-- llm-verify -->\n활성 항목이 없다.\n", encoding="utf-8")
        return 0

    diff = unified_diff(args.backend, args.base, args.head)
    added = added_lines(diff)

    anchor_patterns = sorted({p for r in rules for p in (r.get("anchors") or [])})
    anchor_files, absent, failed = read_files(args.backend, anchor_patterns)
    docs, missing_docs = collect_docs(active, roots)
    baseline, baseline_failed = ({}, [])
    if needs_baseline:
        baseline, baseline_failed = collect_baseline(args.infra)
    conflicts, intentional = conflict_map(
        Path(args.common) / ".github/llm-verify/known-conflicts.yml")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        print("GEMINI_API_KEY 가 없다", file=sys.stderr)
        return 1

    by_stage = defaultdict(list)
    for it in active.values():
        by_stage[it.get("ci_stage", 1)].append(it)

    if args.dry_run:
        print(f"매칭 규칙   {', '.join(r['id'] for r in rules)}"
              + ("  (기본 규칙)" if fallback else ""))
        print(f"변경 파일   {len(files)}건")
        print(f"활성 항목   {len(active)}건")
        for s in (1, 2):
            print(f"  {s}단계    {len(by_stage.get(s, []))}건")
        by_repo = defaultdict(int)
        for it in active.values():
            by_repo[it["repo"]] += 1
        print(f"  저장소별  {dict(by_repo)}")
        print(f"앵커 파일   읽음 {len(anchor_files)}, 부재 {len(absent)}, 실패 {len(failed)}")
        print(f"기준 문서   {len(docs)}건" + (f", 못 읽음 {missing_docs}" if missing_docs else ""))
        print(f"확정값      " + (f"{len(baseline)}건" if needs_baseline else "불필요")
              + (f", 못 읽음 {baseline_failed}" if baseline_failed else ""))
        print(f"모순 유보   {len([i for i in active if i in conflicts])}건")
        eff = [i for i in active if i in intentional and i not in conflicts]
        shadow = [i for i in active if i in intentional and i in conflicts]
        print(f"의도된 이탈 {len(eff)}건"
              + (f" (모순으로 가려진 것 {len(shadow)}건: {', '.join(shadow)})" if shadow else ""))
        for s in CI_STAGES:
            batch = by_stage.get(s, [])
            if batch:
                p = build_prompt(batch, diff, anchor_files if s == 1 else {},
                                 absent, docs, conflicts, intentional,
                                 baseline if s == 2 else None)
                print(f"프롬프트 {s}단계  {len(p):,}자 (대략 {len(p)//2:,} 토큰)")
        return 0

    results, stages = [], {}
    stage1_ok = True
    for stage in CI_STAGES:
        batch = by_stage.get(stage, [])
        if not batch:
            continue
        if stage == 2 and not stage1_ok:
            stages[2] = {"error": "1단계가 온전하지 않아 건너뜀", "complete": False, "detail": "", "n": 0}
            continue
        # 확정값은 2단계에만 넣는다. 값을 대조하는 항목(REL, INF)이 전부 거기 있다
        chunks = [batch[i:i + CHUNK] for i in range(0, len(batch), CHUNK)]
        got, errs, partial = [], [], []
        for n, chunk in enumerate(chunks, 1):
            ids = [i["id"] for i in chunk]
            prompt = build_prompt(chunk, diff, anchor_files if stage == 1 else {},
                                  absent, docs, conflicts, intentional,
                                  baseline if stage == 2 else None)
            resp, err = call_gemini(api_key, prompt, ids)
            if err:
                errs.append(f"{n}/{len(chunks)}: {err}")
                continue
            if not resp["complete"]:
                partial.append(f"{n}/{len(chunks)}: {resp['detail']}")
            got += [r for r in resp["results"] if r["id"] in active]

        complete = not errs and not partial
        detail = "; ".join(errs + partial)
        stages[stage] = {"error": "; ".join(errs) if errs else None,
                         "complete": complete, "detail": detail, "n": len(got),
                         "chunks": len(chunks)}
        if stage == 1 and not complete:
            stage1_ok = False
        results += got

    judged = {r["id"] for r in results}
    unjudged = [i for i in active if i not in judged]

    kept, suppressed = suppress_deferred(results, active)
    violations = [r for r in kept if r["verdict"] == "VIOLATION"]
    conflicting = [r for r in kept if r["verdict"] == "CONFLICTING_BASELINE"]
    insufficient = [r for r in kept if r["verdict"] == "INSUFFICIENT_EVIDENCE"]
    new, existing = split_new(violations, added)

    counts = defaultdict(int)
    for r in kept:
        counts[r["verdict"]] += 1
    counts["UNJUDGED"] = len(unjudged)

    by_repo = defaultdict(int)
    for it in active.values():
        by_repo[it["repo"]] += 1

    ctx = {
        "rules": [r["id"] for r in rules], "fallback": fallback,
        "active": active, "active_n": len(active), "by_repo": by_repo,
        "deferred": deferred_to_local,
        "stages": stages, "new": new, "existing": existing,
        "conflicting": conflicting, "insufficient": insufficient,
        "unjudged": unjudged, "counts": counts,
        "missing_anchors": failed + missing_docs + baseline_failed,
        "absent": absent, "suppressed": suppressed,
    }
    Path(args.out).write_text(render(ctx), encoding="utf-8")
    print(f"활성 {len(active)} / 판정 {len(judged)} / 위반 {len(violations)} "
          f"(신규 {len(new)}) / 미판정 {len(unjudged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
