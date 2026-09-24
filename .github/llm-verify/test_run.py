#!/usr/bin/env python3
"""
run.py 의 회귀 시험.

세 저장소의 G-PR 을 이 도구 하나가 돌리는데 여태 시험이 없었다. 2026-09-24 에 앵커 예산이
이번 PR 과 무관한 파일에 다 쓰여 판정 대상이 통째로 잘리는 것을 사람이 눈으로 찾았다.
그런 종류의 고장은 조용해서, 보고서의 "읽지 못한 앵커" 줄을 안 읽으면 게이트가 돈 것으로
보인다. 그래서 이 파일이 그 함수의 계약을 못 박는다.

read_files 를 먼저 덮는다. 입출력이 순수하고 파일 시스템만 읽어 시험하기 쉽다.

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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
