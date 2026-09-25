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

_envelope_of 와 _parse_results 와 _usage_of 와 _retryable 은 Gemini CLI 로 갈아탄 뒤에
생겼다. Codex 는 --output-schema 로 응답 모양을 서버에서 강제했는데 Gemini CLI 에는 그
플래그가 없어서, 모양을 지키는 책임이 서버에서 이 네 함수로 내려왔다. 모양이 깨진 응답을
통과시키면 그 항목이 조용히 OK 로 흘러 게이트가 무력해지므로 여기서 계약을 못 박는다.

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


class EnvelopeTest(unittest.TestCase):
    """
    _envelope_of 는 CLI 의 stdout 에서 json 봉투를 꺼낸다.

    CLI 가 봉투 앞에 진행 로그를 섞어 찍는 일이 있어서, 첫 중괄호부터 잘라 보는 길을 둔다.
    못 읽으면 빈 사전을 준다. 여기서 예외를 던지면 진짜 실패 사유가 그 예외에 덮인다.
    """

    def test_봉투를_읽는다(self):
        got = run._envelope_of('{"response": "본문", "stats": {}}')
        self.assertEqual(got["response"], "본문")

    def test_앞에_로그가_섞여도_읽는다(self):
        got = run._envelope_of('Reading prompt from stdin...\n{"response": "본문"}')
        self.assertEqual(got["response"], "본문")

    def test_중괄호가_없으면_빈_사전이다(self):
        self.assertEqual(run._envelope_of("그냥 로그"), {})

    def test_깨진_json_이면_빈_사전이다(self):
        self.assertEqual(run._envelope_of('{"response": '), {})

    def test_목록이_와도_빈_사전이다(self):
        """봉투는 객체다. 목록을 사전처럼 쓰면 부르는 쪽에서 터진다."""
        self.assertEqual(run._envelope_of('[1, 2]'), {})

    def test_비어_있으면_빈_사전이다(self):
        self.assertEqual(run._envelope_of(""), {})
        self.assertEqual(run._envelope_of(None), {})


class ParseResultsTest(unittest.TestCase):
    """
    _parse_results 는 response 문자열에서 판정 목록을 꺼내고 모양을 검증한다.

    이 클래스가 이 파일에서 가장 중요하다. 모양 검증이 느슨하면 깨진 응답이 판정으로 들어가고,
    점검 항목 대부분이 "무언가가 없다" 를 묻기 때문에 그 결과가 조용한 OK 로 흐른다.
    """

    def test_판정_목록을_꺼낸다(self):
        got, err = run._parse_results(
            '{"results": [{"id": "A-1", "verdict": "OK", "file": null,'
            ' "line": null, "reason": "근거", "fix": null}]}')
        self.assertIsNone(err)
        self.assertEqual(got[0]["id"], "A-1")

    def test_코드_펜스를_벗긴다(self):
        """모델이 ```json 으로 감싸는 일이 흔하다. 스키마 강제가 없어 더 흔하다."""
        got, err = run._parse_results(
            '```json\n{"results": [{"id": "A-1", "verdict": "OK"}]}\n```')
        self.assertIsNone(err)
        self.assertEqual(len(got), 1)

    def test_이름_없는_펜스도_벗긴다(self):
        got, err = run._parse_results(
            '```\n{"results": [{"id": "A-1", "verdict": "OK"}]}\n```')
        self.assertIsNone(err)
        self.assertEqual(len(got), 1)

    def test_빈_목록도_받는다(self):
        """판정할 것이 없다는 답은 모양이 깨진 것과 다르다."""
        got, err = run._parse_results('{"results": []}')
        self.assertIsNone(err)
        self.assertEqual(got, [])

    def test_response_가_비면_파싱_실패다(self):
        got, err = run._parse_results("")
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_response_가_문자열이_아니면_파싱_실패다(self):
        got, err = run._parse_results({"results": []})
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_json_이_아니면_파싱_실패다(self):
        got, err = run._parse_results("판정해 봤는데 위반은 없었다")
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_results_가_없으면_파싱_실패다(self):
        got, err = run._parse_results('{"verdicts": []}')
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_results_가_목록이_아니면_파싱_실패다(self):
        got, err = run._parse_results('{"results": {"A-1": "OK"}}')
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_id_가_없으면_파싱_실패다(self):
        got, err = run._parse_results('{"results": [{"verdict": "OK"}]}')
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_모르는_verdict_는_파싱_실패다(self):
        """이것이 이 클래스의 핵심이다. 통과시키면 그 항목이 조용히 OK 로 흐른다."""
        got, err = run._parse_results('{"results": [{"id": "A-1", "verdict": "PASS"}]}')
        self.assertIsNone(got)
        self.assertIn("A-1", err)
        self.assertIn("PASS", err)

    def test_항목이_객체가_아니면_파싱_실패다(self):
        got, err = run._parse_results('{"results": ["A-1"]}')
        self.assertIsNone(got)
        self.assertTrue(err.startswith("파싱 실패"))

    def test_다섯_verdict_를_모두_받는다(self):
        items = ", ".join(f'{{"id": "A-{i}", "verdict": "{v}"}}'
                          for i, v in enumerate(run.VERDICTS))
        got, err = run._parse_results('{"results": [%s]}' % items)
        self.assertIsNone(err)
        self.assertEqual(len(got), len(run.VERDICTS))


class UsageOfTest(unittest.TestCase):
    """
    _usage_of 는 봉투의 stats 에서 모델 이름과 토큰 수를 건진다.

    Gemini 의 tokens 키에는 token 이라는 낱말이 없다. 그래서 "이름에 token 이 들어간 정수를
    모은다" 는 Codex 시절 방식으로는 하나도 못 건진다. 자리를 고정해 읽는다는 것을 못 박는다.
    """

    def test_토큰_수와_모델을_건진다(self):
        env = {"stats": {"models": {"gemini-2.5-pro": {
            "tokens": {"prompt": 100, "candidates": 20, "total": 120,
                       "cached": 0, "thoughts": 0, "tool": 0}}}}}
        usage, model = run._usage_of(env)
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(usage, {"prompt": 100, "candidates": 20, "total": 120})

    def test_모델_둘이면_항목별로_더한다(self):
        env = {"stats": {"models": {
            "a": {"tokens": {"total": 10}},
            "b": {"tokens": {"total": 5}}}}}
        usage, model = run._usage_of(env)
        self.assertEqual(usage["total"], 15)
        self.assertEqual(model, "a, b")

    def test_stats_가_없으면_빈_값이다(self):
        self.assertEqual(run._usage_of({}), ({}, ""))
        self.assertEqual(run._usage_of(None), ({}, ""))

    def test_tokens_자리가_바뀌면_빈_값이다(self):
        """키가 바뀐 것을 조용히 0 으로 적지 않는다. 사용량이 안 보이면 로그가 그렇게 말한다."""
        env = {"stats": {"models": {"a": {"usage": {"total": 10}}}}}
        self.assertEqual(run._usage_of(env), ({}, "a"))

    def test_불리언은_수로_세지_않는다(self):
        env = {"stats": {"models": {"a": {"tokens": {"total": 10, "cached": True}}}}}
        usage, _ = run._usage_of(env)
        self.assertEqual(usage, {"total": 10})


class RetryableTest(unittest.TestCase):
    """
    _retryable 은 무엇을 다시 부를지 정한다.

    한도 초과에 재시도를 태우면 판정 없이 예산만 탄다. 반대로 모양이 흔들린 응답을 한 번도
    다시 안 부르면, 스키마 강제가 없어진 뒤로는 단계 하나가 통째로 UNJUDGED 가 된다.
    """

    def test_시간_초과는_끝까지_다시_부른다(self):
        self.assertTrue(run._retryable("시간 초과 (900초)", 0))
        self.assertTrue(run._retryable("시간 초과 (900초)", 1))

    def test_네트워크_오류는_다시_부른다(self):
        self.assertTrue(run._retryable("실행 실패: ECONNRESET", 0))

    def test_파싱_실패는_한_번만_다시_부른다(self):
        self.assertTrue(run._retryable("파싱 실패: results 목록이 없다", 0))
        self.assertFalse(run._retryable("파싱 실패: results 목록이 없다", 1))

    def test_한도_초과는_다시_부르지_않는다(self):
        err = "실행 실패: You've hit your usage limit. Upgrade to Plus"
        self.assertFalse(run._retryable(err, 0))

    def test_종료_코드만으로는_다시_부르지_않는다(self):
        self.assertFalse(run._retryable("실행 실패 (종료 1): stderr: 알 수 없다", 0))


class FailureReasonEnvelopeTest(unittest.TestCase):
    """
    Gemini CLI 는 실패 사유를 봉투의 error 에 담는다. 줄마다 찍던 Codex 이벤트가 아니다.

    2026-09-24 회차에서 판정 383건이 전부 UNJUDGED 로 끝났는데 보고서에 남은 것이
    진행 안내뿐이었다. 봉투를 안 보면 그 일이 그대로 되풀이된다.
    """

    class Proc:
        def __init__(self, stdout="", stderr="", returncode=1):
            self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    def test_봉투의_error_를_읽는다(self):
        proc = self.Proc(
            stdout='{"error": {"type": "Error", "message": "한도 초과", "code": 429}}',
            stderr="Reading prompt from stdin...")
        reason = run._failure_reason(proc)
        self.assertIn("한도 초과", reason)
        self.assertIn("429", reason)
        self.assertNotIn("Reading prompt", reason)

    def test_코드가_없어도_읽는다(self):
        proc = self.Proc(stdout='{"error": {"message": "인증 실패"}}')
        self.assertEqual(run._failure_reason(proc), "인증 실패")

    def test_error_가_문자열이어도_읽는다(self):
        proc = self.Proc(stdout='{"error": "그냥 문자열"}')
        self.assertEqual(run._failure_reason(proc), "그냥 문자열")

    def test_봉투에_error_가_없으면_꼬리를_남긴다(self):
        proc = self.Proc(stdout='{"response": "본문"}', stderr="알 수 없는 실패")
        reason = run._failure_reason(proc)
        self.assertIn("알 수 없는 실패", reason)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
