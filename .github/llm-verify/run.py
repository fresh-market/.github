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
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import yaml

# 판정 엔진은 Codex CLI 를 비대화 모드로 부른다.
#
# HTTP 를 직접 치지 않고 CLI 를 거치는 이유는 인증과 모델 접근을 CLI 가 맡기 때문이다.
# 러너는 `codex login --with-api-key` 로 한 번 로그인해 두고, 여기서는 그것을 쓴다.
# 프롬프트는 stdin 으로 넣고 답은 --output-schema 로 모양을 고정해 -o 파일로 받는다.
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")

# 모델을 비워 두면 Codex 의 기본값을 쓴다.
#
# 기본값을 코드에 박지 않는 이유는 모델 이름이 자주 바뀌고, 틀린 이름을 박아 두면
# 판정이 통째로 실패하기 때문이다. 고정하려면 워크플로에서 CODEX_MODEL 을 준다.
CODEX_MODEL = os.environ.get("CODEX_MODEL", "")

# 호출 하나의 시간 상한. 에이전트가 여러 턴을 돌 수 있어 HTTP 때보다 넉넉히 준다.
CALL_TIMEOUT_SEC = 900

# CI 가 판정하는 단계. 1단계가 backend, 2단계가 common + infra 다.
#
# CI 는 아직 1단계만 본다. 2단계는 G-LOCAL 이 --full 로 맡는다.
# 근거였던 Gemini 무료 티어의 분당 한도는 엔진을 바꾸면서 사라졌으므로,
# 이 값은 (1, 2) 로 여는 것을 전제로 남겨 둔다. 항목의 ci_stage 는 그대로다.
CI_STAGES = (1,)

# 한 호출에 넣는 항목 수.
#
# 나눠 부르면 호출당 출력이 줄어 MAX_TOKENS 를 넘길 일이 없고, 한 덩어리가 실패해도
# 나머지 판정은 살아남는다. 대신 build_prompt 가 덩어리마다 기준 문서와 앵커를 다시 실어
# 입력이 덩어리 수만큼 곱해진다. 50 으로 자르면 200건짜리 PR 에서 입력이 3.8배가 된다.
#
# 사고 예산을 묶은 뒤로는 한 번에 200건도 출력이 들어갈 수 있다.
# 들어가면 곱해지는 문제가 사라지므로 크게 잡고, MAX_TOKENS 가 나면 줄인다.
CHUNK = 200

VERDICTS = ["VIOLATION", "OK", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE", "CONFLICTING_BASELINE"]


# --- 유틸 ---------------------------------------------------------------

def git(cwd, *args):
    # core.quotepath 를 끈다. 기본값이 켜짐이라 비ASCII 경로를 따옴표로 감싸고
    # 바이트를 \353 같은 8진수로 바꿔 내놓는다. 그러면 앵커 글롭이 하나도 안 맞아
    # 한글 이름 문서를 바꾼 커밋이 "변경 없음" 으로 계산된다.
    r = subprocess.run(["git", "-C", str(cwd), "-c", "core.quotepath=false", *args],
                       capture_output=True, text=True)
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

    git 이 추적하지 않는 파일은 읽지 않는다. QueryDSL 이 build/generated 에 만든 Q클래스가
    앵커 글롭에 걸리는데, CI 는 새로 체크아웃해 build 가 없고 로컬은 빌드한 뒤라 있다.
    그대로 두면 같은 커밋인데 판정 입력이 로컬과 CI 에서 달라진다.
    """
    root = Path(root)
    try:
        tracked = set(git(root, "ls-files").splitlines())
    except RuntimeError:
        tracked = None
    got, absent, failed, total = {}, [], [], 0
    for pattern in patterns:
        hits = [f for f in sorted(root.glob(pattern)) if f.is_file()]
        if tracked is not None:
            hits = [f for f in hits if str(f.relative_to(root)) in tracked]
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


# --- DDL 좁히기 ---------------------------------------------------------

TABLE_RE = re.compile(r"^CREATE TABLE (\w+)", re.M)
REF_RE = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.I)
JPA_TABLE_RE = re.compile(r'@Table\s*\(\s*name\s*=\s*"(\w+)"')


def snake(name):
    """FreshOrder -> fresh_order. @Table 이 없을 때 JPA 기본 전략을 흉내낸다."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def slice_ddl(text, wanted):
    """
    스키마에서 필요한 테이블 정의만 남긴다.

    엔티티 하나를 고쳐도 32개 테이블 7만 자가 통째로 붙던 것을 줄인다.
    FK 로 한 단계 이어진 테이블까지 함께 남긴다. 참조 대상이 빠지면 제약의 근거가 끊긴다.
    이 스키마는 복합 외래 키로 조상 키를 복제하는 설계라 테이블 사이 결합이 보통보다 강하다.

    무엇 하나라도 못 찾으면 통째로 돌려준다. 잘라서 근거를 잃는 것보다 큰 편이 낫다.
    """
    blocks, order = {}, []
    for m in TABLE_RE.finditer(text):
        name = m.group(1)
        end = text.find("\nCREATE TABLE ", m.end())
        blocks[name] = text[m.start():end if end != -1 else len(text)]
        order.append(name)
    if not blocks or not wanted or not wanted <= set(blocks):
        return text, None

    keep = set(wanted)
    for t in list(wanted):
        keep |= {r for r in REF_RE.findall(blocks[t]) if r in blocks}
    head = text[:text.find("CREATE TABLE")] if "CREATE TABLE" in text else ""
    body = "\n".join(blocks[t] for t in order if t in keep)
    note = (f"-- 전체 {len(blocks)}개 중 {len(keep)}개만 실었다. "
            f"바뀐 엔티티가 쓰는 테이블과 FK 로 이어진 것이다.\n"
            f"-- 나머지는 이 변경과 무관하다.\n")
    return head + note + body, (len(keep), len(blocks))


def tables_in_diff(text, changed_lines):
    """
    바뀐 줄이 어느 테이블 정의 안에 있는지 찾는다.

    SQL 만 고친 커밋에서는 엔티티가 기준이 될 수 없다. 아직 엔티티가 없는 테이블을
    고쳤을 때 정작 그 테이블이 빠지기 때문이다. 바뀐 줄의 위치로 직접 찾는다.
    """
    names, start, cur = set(), {}, None
    for n, line in enumerate(text.splitlines(), 1):
        m = TABLE_RE.match(line)
        if m:
            cur = m.group(1)
            start[cur] = n
        if cur and n in changed_lines:
            names.add(cur)
    return names


def tables_of(java_texts):
    """자바 소스에서 테이블 이름을 뽑는다. @Table 이 없으면 클래스명을 스네이크로 바꾼다."""
    names = set()
    for path, text in java_texts.items():
        m = JPA_TABLE_RE.search(text)
        if m:
            names.add(m.group(1))
        elif "@Entity" in text:
            names.add(snake(Path(path).stem))
    return names


def collect_docs(active, roots):
    """활성 항목이 속한 판정 기준 문서만 읽는다."""
    # roots 는 source 로 라벨된다. 판정 대상에 따라 없는 키가 있을 수 있다.
    sub = {"common": "docs/software-quality",
           "backend": "docs/code-architecture",
           "infra": "docs/infra-review"}
    doc_dirs = {k: Path(roots[k]) / sub[k] for k in sub if roots.get(k)}
    wanted = defaultdict(set)
    for it in active.values():
        wanted[it["repo"]].add(it["doc"])
    docs, missing = {}, []
    for repo, names in wanted.items():
        if repo not in doc_dirs:
            missing += [f"{repo}/{n}" for n in sorted(names)]
            continue
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
8. 해당 없는 필드는 null 로 둔다. 위반이 아니면 file, line, fix 가 null 이다.
9. reason 과 fix 는 한국어로 각각 한 문장씩 쓴다.
   다만 항목 ID, verdict, 파일 경로, 클래스명, 메서드명, 설정 키와 값은 원문 그대로 둔다.
   번역하면 검색과 대조가 깨진다.
"""

# 구조화 출력 스키마.
#
# 엄격 모드라 객체마다 additionalProperties 를 false 로 두고 모든 속성을 required 에 넣어야 한다.
# 넣지 않으면 호출이 400 으로 거절된다. 실제로 그 오류로 판정이 통째로 죽은 적이 있다.
#   Invalid schema for response_format: 'additionalProperties' is required to be supplied and to be false
#
# 그래서 "선택 필드" 를 required 에서 빼는 방식이 안 된다. 대신 null 을 허용해 같은 뜻을 만든다.
# 위반이 아닌 항목은 file, line, reason, fix 를 null 로 답한다.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "file": {"type": ["string", "null"]},
                    "line": {"type": ["integer", "null"]},
                    "reason": {"type": ["string", "null"]},
                    "fix": {"type": ["string", "null"]},
                },
                "required": ["id", "verdict", "file", "line", "reason", "fix"],
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


def call_judge(prompt, expected_ids, attempts=3):
    """
    일시적 실패에 재시도한다.

    재시도가 없으면 한 번의 일시 실패로 그 단계가 죽고 항목 전부가 UNJUDGED 가 된다.
    그건 게이트가 없는 것과 같다.
    응답이 왔는데 형식이 어긋난 경우는 재시도하지 않는다. 다시 불러도 같기 때문이다.
    """
    last = None
    for n in range(attempts):
        result, err = _call_once(prompt, expected_ids)
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
    """
    일시적인 것만 다시 부른다.

    스키마를 못 맞췄거나 항목이 빠진 응답은 다시 불러도 같으므로 재시도하지 않는다.
    한도 초과도 뺀다. 거부된 호출도 사용량에 잡히므로 다시 부르면 판정 없이 예산만 태운다.

    종료 코드가 0이 아니라는 것만으로 다시 부르지 않는다. 스키마가 거절당한 경우가 그런데,
    같은 요청을 다시 보내면 같은 400 이 온다. 실제로 그 오류에 재시도 세 번을 태운 적이 있다.
    네트워크와 시간 초과처럼 다시 부를 이유가 분명한 것만 남긴다.
    """
    return any(s in err for s in ("시간 초과", "timed out", "connection",
                                 "ECONNRESET", "ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN"))


def _call_once(prompt, expected_ids):
    """
    Codex CLI 를 한 번 부른다.

    프롬프트는 stdin 으로 넣는다. `codex exec` 는 인자가 없으면 stdin 을 프롬프트로 읽는다.
    Gemini 의 systemInstruction 자리가 없어 SYSTEM 을 앞에 붙인다.

    샌드박스를 read-only 로 두는 이유는 판정이 파일을 고칠 일이 없기 때문이다.
    프롬프트에 diff 와 앵커와 기준 문서가 이미 다 들어 있어 저장소를 뒤질 필요도 없다.
    작업 루트를 빈 임시 디렉터리로 주어 그 사실을 구조로 강제한다.
    """
    with tempfile.TemporaryDirectory(prefix="llm-verify-") as tmp:
        schema_path = Path(tmp) / "schema.json"
        out_path = Path(tmp) / "last-message.json"
        schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")

        cmd = [CODEX_BIN, "exec",
               "--sandbox", "read-only",
               "--cd", tmp,
               "--skip-git-repo-check",
               "--ephemeral",
               "--ignore-user-config",
               "--color", "never",
               "--json",
               "--output-schema", str(schema_path),
               "--output-last-message", str(out_path)]
        if CODEX_MODEL:
            cmd += ["--model", CODEX_MODEL]

        try:
            proc = subprocess.run(cmd, input=SYSTEM + "\n\n" + prompt,
                                  capture_output=True, text=True,
                                  timeout=CALL_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            return None, f"시간 초과 ({CALL_TIMEOUT_SEC}초)"
        except FileNotFoundError:
            return None, f"실행 실패: {CODEX_BIN} 를 찾을 수 없다"

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-300:]
            return None, f"실행 실패 (종료 {proc.returncode}): {tail}"

        if not out_path.is_file():
            return None, "실행 실패: 마지막 메시지 파일이 없다"

        try:
            results = json.loads(out_path.read_text(encoding="utf-8"))["results"]
        except Exception as e:
            return None, f"파싱 실패: {e}"

        model, usage, kinds = _usage_of(proc.stdout, proc.stderr)
        log_usage(f"{len(expected_ids)}건", len(prompt), model, usage, kinds,
                  proc.stdout, proc.stderr)

    seen = {r["id"] for r in results}
    ok = seen == set(expected_ids)
    detail = "" if ok else f"응답 {len(seen)} / 요청 {len(expected_ids)}"
    return {"results": results, "usage": usage, "model": model,
            "complete": ok, "detail": detail}, None


def _usage_of(stdout, stderr):
    """
    CLI 가 --json 으로 뱉은 이벤트에서 모델 이름과 토큰 사용량을 건진다.

    Gemini 는 usageMetadata 를 응답에 실어 줬는데 CLI 에는 그 자리가 없다.
    이벤트 스키마는 판올림마다 바뀔 수 있으므로 키 이름을 넓게 훑는다.
    이름에 token 이 들어간 정수와 model 로 보이는 문자열을 모은다.
    못 건져도 판정은 계속한다. 사용량은 비용을 보기 위한 것이지 판정에 쓰이지 않는다.
    """
    model, usage, kinds = None, {}, []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type") or ev.get("event") or ev.get("msg", {}).get("type")
        if isinstance(kind, str) and kind not in kinds:
            kinds.append(kind)
        stack = [ev]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
                    elif isinstance(v, int) and "token" in k.lower():
                        usage[k] = v
                    # 키 이름을 고정하지 않는다. 판올림마다 model, model_slug,
                    # effective_model 처럼 이름이 갈려서 하나만 보면 놓친다
                    elif isinstance(v, str) and "model" in k.lower() and v:
                        model = model or v
            elif isinstance(o, list):
                stack.extend(o)
    return model, usage, kinds


def log_usage(label, prompt_chars, model, usage, kinds, stdout, stderr):
    """
    호출 하나의 비용 근거를 남긴다.

    못 건졌으면 그 사실과 함께 CLI 출력의 끝부분을 남긴다.
    형식을 모르는 채로 다음 판올림을 기다리는 것보다 한 번 보고 고치는 편이 빠르다.
    """
    if usage:
        parts = ", ".join(f"{k} {v:,}" for k, v in sorted(usage.items()))
        print(f"  사용량 {label}  모델 {model or '?'}  {parts}  (프롬프트 {prompt_chars:,}자)",
              file=sys.stderr)
        # 모델만 못 건졌으면 어떤 이벤트가 오갔는지 남긴다. 다음 판에서 키를 맞추는 근거다
        if not model and kinds:
            print(f"    모델 이름을 못 찾았다. 이벤트 종류: {', '.join(kinds[:12])}",
                  file=sys.stderr)
    else:
        tail = ((stderr or "") + (stdout or ""))[-400:].replace("\n", " | ")
        print(f"  사용량 {label}  모델 {model or '?'}  토큰 정보를 못 찾았다 "
              f"(프롬프트 {prompt_chars:,}자). 출력 끝: {tail}", file=sys.stderr)


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
    # push 마다 새 코멘트가 달리므로 어느 커밋에 대한 판정인지 머리에 적는다.
    # 없으면 코멘트가 쌓였을 때 어느 것이 지금 코드에 대한 것인지 알 수 없다.
    L = ["<!-- llm-verify -->", "## LLM 검증 (G-PR)", "",
         f"커밋 `{ctx['head'][:7]}` 판정, {ctx['at']}", ""]
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
    # match 전용. 활성 항목 목록을 여기 쓴다. 주지 않으면 쓰지 않는다.
    # --out 과 나누는 이유는 CI 가 --out 을 판정 코멘트에 쓰기 때문이다.
    ap.add_argument("--items-out", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM 을 부르지 않고 무엇이 활성화되어 어떤 입력이 만들어지는지만 본다")
    args = ap.parse_args()

    anchors = load_yaml(Path(args.backend) / ".github/llm-verify/anchors.yml")
    files = changed_files(args.backend, args.base, args.head)
    rules, fallback = match_rules(anchors, files)
    needs_baseline = any(r.get("needs_baseline_values") for r in rules)

    # 판정 대상이 하나도 안 바뀌었으면 판정하지 않는다.
    # 어떤 규칙에도 안 걸린 데다 코드도 안 바뀐 것은 답이 정해진 질문이다.
    code_globs = anchors["defaults"].get("code_globs") or []
    code_changed = (not code_globs) or matches_any(files, code_globs)
    skip = fallback and not code_changed

    if args.mode == "match":
        out = os.environ.get("GITHUB_OUTPUT")
        # 확정값 문서는 29만 자라 판정 입력에서 가장 크다. 규칙이 걸렸다는 이유만으로
        # 통째로 읽으면 그것만으로 컨텍스트가 찬다. 값을 대조하는 항목은 REL 과 INF 뿐이므로
        # 그것이 실제로 활성일 때만 읽으라고 알려준다.
        # 레지스트리를 역할 이름이 아니라 items.yml 의 source 로 라벨한다.
        # --backend 는 "판정 대상" 이라는 뜻이라 infra 를 대상으로 돌리면 그 자리에 infra 가 온다.
        # 역할 이름으로 라벨하면 infra 항목이 backend 로 찍혀 자기 항목을 0건으로 센다.
        # source 로 라벨하면 같은 저장소가 두 자리에 와도 하나로 합쳐진다.
        registries = {}
        for path in (args.backend, args.common, args.infra):
            # CI 의 match 단계는 --backend 만 준다. 없는 경로는 건너뛴다.
            if not path:
                continue
            f = Path(path) / ".github/llm-verify/items.yml"
            if not f.is_file():
                continue
            d = load_yaml(f)
            registries.setdefault(d.get("source") or str(path),
                                  d["items"] if isinstance(d, dict) else d)
        active = active_items(rules, registries)
        baseline_ids = sorted(i for i in active
                              if i.startswith("REL-") or i.startswith("INF-"))
        # 로컬의 기본 판정 범위는 "이 저장소 자신의 항목" 이다.
        # ci_stage 로 가르면 backend 기준이라 infra 에서 돌릴 때 1단계가 0건이 된다.
        # 대상 저장소가 items.yml 의 source 로 자신을 밝히므로 그것과 맞춰 가른다.
        own = load_yaml(Path(args.backend) / ".github/llm-verify/items.yml").get("source")
        mine = [i for i, it in active.items() if it["repo"] == own]
        payload = {
            "skip": "true" if skip else "false",
            "code_changed": "true" if code_changed else "false",
            "needs_baseline": "true" if needs_baseline and baseline_ids else "false",
            "baseline_items": str(len(baseline_ids)),
            "active": str(len(active)),
            "source": own or "?",
            "own": str(len(mine)),
            "other": str(len(active) - len(mine)),
            "rules": ",".join(r["id"] for r in rules),
            "changed": str(len(files)),
        }
        if out:
            with open(out, "a") as f:
                for k, v in payload.items():
                    f.write(f"{k}={v}\n")
        print(json.dumps(payload, ensure_ascii=False))

        # 활성 항목 목록을 파일로 낸다.
        # 이것이 없으면 판정하는 쪽이 items.yml 세 개(합계 17만 자)를 읽어 직접 걸러야 한다.
        # 실제로 필요한 것은 활성 항목뿐이고 그것은 7천 자 안팎이다.
        # skip 이어도 목록은 그대로 쓴다. 건너뛸지는 부르는 쪽이 정한다.
        # verify.sh 는 --full 이면 건너뛰지 않고 다른 저장소 항목을 판정한다.
        if args.items_out:
            L = [f"# 활성 점검 항목 {len(active)}건",
                 f"# 대상 {own}  범위 {args.base[:7]}..{args.head[:7]}",
                 f"# 규칙 {', '.join(r['id'] for r in rules)}", ""]

            # 스키마에서 어느 테이블을 볼지 알려준다.
            # 판정하는 쪽이 이것을 모르면 811줄 7만 자를 통째로 읽는다.
            anchor_pats = sorted({p for r in rules for p in (r.get("anchors") or [])})
            if any(p.endswith(".sql") for p in anchor_pats):
                java, _, _ = read_files(args.backend, ["**/domain/entity/*.java"])
                changed_java = {f: t for f, t in java.items() if f in files}
                added_here = added_lines(unified_diff(args.backend, args.base, args.head))
                sqls, _, _ = read_files(args.backend, [p for p in anchor_pats if p.endswith(".sql")])
                for path, text in sqls.items():
                    # judge 모드와 같은 기준으로 고른다. 둘이 갈리면 로컬과 CI 가 다른 것을 본다.
                    want = tables_in_diff(text, added_here.get(path, set()))
                    want |= tables_of(changed_java)
                    want = want or tables_of(java)
                    _, info = slice_ddl(text, want)
                    if not info:
                        continue
                    L += [f"## 스키마 {path}",
                          f"이 변경과 관련된 테이블 {info[0]}개만 본다 (전체 {info[1]}개).",
                          f"직접 관련된 것: {', '.join(sorted(want))}",
                          "여기에 FK 로 이어진 테이블까지 함께 본다. 나머지는 읽지 않는다.", ""]
            for repo in sorted({it["repo"] for it in active.values()}):
                sel = {i: it for i, it in active.items() if it["repo"] == repo}
                L.append(f"## {repo} {len(sel)}건" + ("  (기본 판정 범위)" if repo == own else "  (--full 일 때만)"))
                for doc in sorted({it["doc"] for it in sel.values()}):
                    L.append(f"\n### {doc}")
                    for i in sorted(k for k, v in sel.items() if v["doc"] == doc):
                        it = sel[i]
                        L.append(f"- `{i}` ({it['ch']}장) {it['title']}")
                        if it.get("criteria"):
                            L.append(f"  - {it['criteria']}")
                L.append("")
            Path(args.items_out).write_text("\n".join(L) + "\n", encoding="utf-8")
        return 0

    # 레지스트리와 문서 경로를 역할 이름이 아니라 items.yml 의 source 로 라벨한다.
    # --backend 는 "판정 대상" 이라는 뜻이라 infra 를 대상으로 돌리면 그 자리에 infra 가 온다.
    # 역할 이름으로 라벨하면 infra 항목이 backend 로 찍혀 자기 항목을 못 찾는다.
    roots, registries = {}, {}
    for path in (args.backend, args.common, args.infra):
        if not path:
            continue
        f = Path(path) / ".github/llm-verify/items.yml"
        if not f.is_file():
            continue
        d = load_yaml(f)
        src = d.get("source") or str(path)
        roots.setdefault(src, path)
        registries.setdefault(src, d["items"] if isinstance(d, dict) else d)

    active = active_items(rules, registries)

    # CI 는 판정 대상 저장소 자신의 항목만 본다. 나머지는 G-LOCAL 이 --full 로 맡는다.
    #
    # ci_stage 로 가르지 않는 이유는 그 값이 backend 를 전제로 매겨져 있어서다.
    # infra 항목은 전부 2단계라, infra 를 판정 대상으로 돌리면 자기 항목이 0건이 된다.
    # 대상 저장소가 items.yml 의 source 로 자신을 밝히므로 그것과 맞춰 가른다.
    # backend 를 대상으로 할 때는 결과가 ci_stage 1 과 같다.
    #
    # 활성에서 아예 빼는 이유는, 남겨 두면 판정하지 않은 것이 UNJUDGED 로 쌓여
    # 담당이 아니어서 안 본 것과 물었는데 답이 안 온 것이 뒤섞이기 때문이다.
    own_source = load_yaml(Path(args.backend) / ".github/llm-verify/items.yml").get("source")
    deferred_to_local = {i: it for i, it in active.items() if it["repo"] != own_source}
    active = {i: it for i, it in active.items() if i not in deferred_to_local}

    if not active:
        Path(args.out).write_text("<!-- llm-verify -->\n활성 항목이 없다.\n", encoding="utf-8")
        return 0

    diff = unified_diff(args.backend, args.base, args.head)
    added = added_lines(diff)

    anchor_patterns = sorted({p for r in rules for p in (r.get("anchors") or [])})
    anchor_files, absent, failed = read_files(args.backend, anchor_patterns)

    # 스키마는 바뀐 엔티티가 쓰는 테이블만 남긴다. 앵커 분량의 대부분이 이 파일이다.
    # 어느 테이블인지 알 수 없으면 통째로 둔다.
    ddl_note = None
    for path in [k for k in anchor_files if k.endswith(".sql")]:
        changed_java = {f: anchor_files[f] for f in anchor_files
                        if f.endswith(".java") and f in files}
        # SQL 자체가 바뀌었으면 바뀐 줄이 든 테이블이 기준이다.
        # 엔티티가 바뀌었으면 그 엔티티가 쓰는 테이블이 기준이다. 둘 다면 합친다.
        wanted = tables_in_diff(anchor_files[path], added.get(path, set()))
        wanted |= tables_of(changed_java)
        wanted = wanted or tables_of(
            {f: t for f, t in anchor_files.items() if f.endswith(".java")})
        sliced, info = slice_ddl(anchor_files[path], wanted)
        if info:
            anchor_files[path] = sliced
            ddl_note = f"{path} {info[0]}/{info[1]}개 테이블"

    docs, missing_docs = collect_docs(active, roots)
    # 확정값은 2단계 프롬프트에만 들어간다. 2단계를 돌지 않으면 읽어 봐야 쓰이지 않는다.
    # 문서 10개에 29만 자라 읽는 것만으로도 낭비다.
    baseline, baseline_failed = ({}, [])
    if needs_baseline and 2 in CI_STAGES:
        baseline, baseline_failed = collect_baseline(args.infra)
    conflicts, intentional = conflict_map(
        Path(args.common) / ".github/llm-verify/known-conflicts.yml")

    # 인증은 CLI 가 맡는다. 여기서는 그 CLI 가 있는지만 본다.
    # 로그인이 안 되어 있으면 첫 호출이 실패하며 그 사유가 그대로 리포트에 실린다.
    if not args.dry_run and shutil.which(CODEX_BIN) is None:
        print(f"{CODEX_BIN} 를 찾을 수 없다. 러너에서 설치와 로그인을 먼저 한다", file=sys.stderr)
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
        print(f"앵커 파일   읽음 {len(anchor_files)}, 부재 {len(absent)}, 실패 {len(failed)}"
              + (f"  (스키마 {ddl_note})" if ddl_note else ""))
        print(f"기준 문서   {len(docs)}건" + (f", 못 읽음 {missing_docs}" if missing_docs else ""))
        print(f"확정값      " + (f"{len(baseline)}건" if baseline else "불필요")
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
            resp, err = call_judge(prompt, ids)
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
        "head": args.head,
        "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
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
