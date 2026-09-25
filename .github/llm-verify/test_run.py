#!/usr/bin/env python3
"""
run.py 의 회귀 시험.

세 저장소의 G-PR 을 이 도구 하나가 돌리는데 여태 시험이 없었다. 2026-09-24 에 앵커 예산이
이번 PR 과 무관한 파일에 다 쓰여 판정 대상이 통째로 잘리는 것을 사람이 눈으로 찾았다.
그런 종류의 고장은 조용해서, 보고서의 "읽지 못한 앵커" 줄을 안 읽으면 게이트가 돈 것으로
보인다. 그래서 이 파일이 그 함수의 계약을 못 박는다.

read_files 를 먼저 덮는다. 입출력이 순수하고 파일 시스템만 읽어 시험하기 쉽다.
_failure_reason 도 같은 이유로 덮는다. 판정이 실패했을 때 사람이 원인을 볼 수 있느냐가
게이트의 값어치를 좌우하는데, 그것 역시 한 번 조용히 망가진 적이 있다.

    python3 .github/llm-verify/test_run.py
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_run():
    spec = importlib.util.spec_from_file_location("run_under_test", HERE / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_run()


class ReadFilesTest(unittest.TestCase):
    """
    read_files 는 결과를 셋으로 나눈다.

    got     읽은 파일
    absent  패턴에 해당하는 파일이 아예 없다. 부재 판정의 근거다
    failed  있는데 못 읽었다. INSUFFICIENT_EVIDENCE 사유다

    absent 와 failed 를 섞으면 "없어서 통과" 와 "못 봐서 판정 불가" 가 뭉개진다.
    점검 항목의 대부분이 부재를 묻기 때문에 이 구분이 게이트의 실효를 좌우한다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args],
                       check=True, capture_output=True)

    def _write(self, rel, text, track=True):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if track:
            self._git("add", rel)
            self._git("commit", "-q", "-m", "x")
        return rel

    def read(self, patterns, **kw):
        return run.read_files(self.root, patterns, **kw)

    # --- 기본 계약 -------------------------------------------------------

    def test_없는_패턴은_absent_이지_failed_가_아니다(self):
        got, absent, failed = self.read(["src/**/*.java"])
        self.assertEqual(got, {})
        self.assertEqual(absent, ["src/**/*.java"])
        self.assertEqual(failed, [])

    def test_예산을_넘으면_failed_에_사유가_남는다(self):
        self._write("a.java", "x" * 100)
        self._write("b.java", "y" * 100)
        got, absent, failed = self.read(["*.java"], limit_bytes=150)
        self.assertEqual(len(got), 1)
        self.assertEqual(absent, [])
        self.assertEqual(len(failed), 1)
        self.assertIn("용량 상한 초과", failed[0])

    def test_git_이_추적하지_않는_파일은_안_읽는다(self):
        self._write("tracked.java", "a")
        self._write("untracked.java", "b", track=False)
        got, _, failed = self.read(["*.java"])
        self.assertIn("tracked.java", got)
        self.assertNotIn("untracked.java", got)
        self.assertEqual(failed, [])

    def test_같은_파일을_두_패턴이_잡아도_한_번만_읽는다(self):
        self._write("a.java", "x" * 100)
        got, _, failed = self.read(["*.java", "a.java"], limit_bytes=150)
        self.assertEqual(len(got), 1)
        self.assertEqual(failed, [])

    # --- priority (2026-09-24 회차가 만든 계약) ---------------------------

    def test_priority_가_예산을_먼저_쓴다(self):
        """
        이것이 이 파일의 핵심이다.

        부르는 쪽이 글롭을 알파벳순으로 정렬해 넘기므로 뒤쪽 글롭이 늘 손해를 본다.
        2026-09-24 에 service 글롭이 그래서 93개 중 93개를 잃었다.
        """
        self._write("aaa.java", "x" * 100)
        self._write("zzz.java", "y" * 100)

        without = self.read(["*.java"], limit_bytes=150)[0]
        self.assertNotIn("zzz.java", without)

        with_prio = self.read(["*.java"], limit_bytes=150, priority=["zzz.java"])[0]
        self.assertIn("zzz.java", with_prio)
        self.assertNotIn("aaa.java", with_prio)

    def test_priority_는_absent_를_오염시키지_않는다(self):
        """
        priority 는 글롭이 아니라 경로다.

        absent 에 넣으면 "이 패턴에 해당하는 파일이 없다" 라는 뜻이 만들어져
        부재 판정의 근거가 망가진다.
        """
        self._write("a.java", "x")
        got, absent, failed = self.read(
            ["nowhere/**/*.java"], priority=["a.java", "does-not-exist.java"])
        self.assertIn("a.java", got)
        self.assertEqual(absent, ["nowhere/**/*.java"])
        self.assertEqual(failed, [])

    def test_priority_에_없는_경로가_있어도_안_터진다(self):
        self._write("a.java", "x")
        got, _, failed = self.read(["*.java"], priority=["gone.java", "a.java"])
        self.assertEqual(list(got), ["a.java"])
        self.assertEqual(failed, [])

    def test_priority_도_추적_대상만_읽는다(self):
        self._write("untracked.java", "x", track=False)
        got, _, _ = self.read([], priority=["untracked.java"])
        self.assertEqual(got, {})

    def test_priority_와_글롭이_같은_파일을_잡아도_한_번만_읽는다(self):
        self._write("a.java", "x" * 100)
        got, _, failed = self.read(["*.java"], limit_bytes=150, priority=["a.java"])
        self.assertEqual(len(got), 1)
        self.assertEqual(failed, [])

    def test_priority_를_안_주면_예전과_같다(self):
        """기본값이 있어야 priority 를 안 넘기는 다른 호출부가 그대로 돈다."""
        self._write("a.java", "x")
        self.assertEqual(self.read(["*.java"]), self.read(["*.java"], priority=()))

    # --- 경로 다루기 -----------------------------------------------------

    def test_한글_경로도_읽는다(self):
        """infra 의 system-design 문서가 전부 한글 이름이다."""
        self._write("docs/설계문서.md", "내용")
        got, _, failed = self.read(["docs/*.md"], priority=["docs/설계문서.md"])
        self.assertIn("docs/설계문서.md", got)
        self.assertEqual(failed, [])


class FailureReasonTest(unittest.TestCase):
    """
    판정이 실패했을 때 사람이 읽을 이유를 만든다.

    2026-09-24 회차에서 판정이 383건 전부 UNJUDGED 로 끝났는데 보고서에 남은 것이
    "Reading prompt from stdin..." 뿐이었다. CLI 의 진행 안내다. 진짜 이유는 --json 이
    stdout 에 실어 준 이벤트에 있었는데 그쪽을 안 봐서 원인을 아무도 못 짚었다.
    """

    class Proc:
        def __init__(self, stdout="", stderr="", returncode=1):
            self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    def test_stdout_의_오류_이벤트를_읽는다(self):
        proc = self.Proc(
            stdout='{"type":"thread.started"}\n{"type":"error","message":"컨텍스트 초과"}',
            stderr="Reading prompt from stdin...")
        self.assertEqual(run._failure_reason(proc), "컨텍스트 초과")

    def test_stderr_에_이유가_없어도_잃지_않는다(self):
        """이것이 이 클래스의 핵심이다. stderr 만 보면 원인이 통째로 사라진다."""
        proc = self.Proc(
            stdout='{"type":"turn.failed","error":{"message":"토큰 한도"}}',
            stderr="Reading prompt from stdin...")
        self.assertIn("토큰 한도", run._failure_reason(proc))
        self.assertNotIn("Reading prompt", run._failure_reason(proc))

    def test_같은_이유가_두_번_와도_한_번만_적는다(self):
        proc = self.Proc(stdout=(
            '{"type":"error","message":"같은 이유"}\n'
            '{"type":"turn.failed","error":{"message":"같은 이유"}}'))
        self.assertEqual(run._failure_reason(proc), "같은 이유")

    def test_구조화된_이벤트가_없으면_양쪽을_함께_남긴다(self):
        proc = self.Proc(stdout="평범한 출력", stderr="평범한 오류")
        reason = run._failure_reason(proc)
        self.assertIn("평범한 오류", reason)
        self.assertIn("평범한 출력", reason)

    def test_JSON_이_아닌_줄이_섞여도_안_터진다(self):
        proc = self.Proc(stdout='로그 한 줄\n{ 깨진 json\n{"type":"error","message":"진짜"}')
        self.assertEqual(run._failure_reason(proc), "진짜")

    def test_출력이_아예_없으면_그렇게_말한다(self):
        self.assertEqual(run._failure_reason(self.Proc()), "출력이 없다")

    def test_ANSI_색_코드를_지운다(self):
        """이 문자열은 PR 코멘트로 그대로 나간다. 마크다운이 색 코드를 글자로 보여 준다."""
        proc = self.Proc(stderr="\x1b[31m실패했다\x1b[0m")
        reason = run._failure_reason(proc)
        self.assertIn("실패했다", reason)
        self.assertNotIn("\x1b", reason)
        self.assertNotIn("[0m", reason)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
