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


    # --- 글롭별 몫 (2026-09-25 회차가 만든 계약) --------------------------

    def test_뒤쪽_글롭이_앞쪽_글롭에_굶지_않는다(self):
        """
        이것이 이 절의 핵심이다.

        글롭은 알파벳순으로 온다. 앞에서부터 다 주면 뒤쪽이 굶는다. 2026-09-25 에
        마이그레이션 번호를 바꾸는 PR 을 판정하면서 정작 그 마이그레이션 30개 중 27개가
        잘렸다. src/main/resources 가 src/main/java 보다 알파벳순으로 뒤라서다.
        """
        for i in range(4):
            self._write(f"aaa/{i}.java", "x" * 50)
        for i in range(4):
            self._write(f"zzz/{i}.sql", "y" * 50)
        got, _, _ = self.read(["aaa/*.java", "zzz/*.sql"], limit_bytes=200)
        self.assertEqual(sum(1 for k in got if k.startswith("aaa/")), 2)
        self.assertEqual(sum(1 for k in got if k.startswith("zzz/")), 2)

    def test_남은_예산을_버리지_않는다(self):
        """
        몫은 보장선이지 상한이 아니다.

        몫만으로 끊으면 글롭마다 자리가 조금씩 남아 예산이 통째로 버려진다. 실측에서 그
        낭비가 18,674 바이트였고 몫을 넣기 전보다 읽은 파일이 오히려 줄었다.
        """
        self._write("a/big.java", "x" * 90)
        self._write("b/small.java", "y" * 10)
        got, _, failed = self.read(["a/*.java", "b/*.java"], limit_bytes=100)
        self.assertEqual(len(got), 2)
        self.assertEqual(failed, [])

    def test_작은_파일부터_담아_근거를_더_산다(self):
        """같은 예산이면 파일 수가 많은 편이 판정할 수 있는 항목이 많다."""
        self._write("a/x.java", "x" * 100)
        self._write("b/small1.java", "y" * 20)
        self._write("b/small2.java", "z" * 20)
        got, _, _ = self.read(["a/*.java", "b/*.java"], limit_bytes=60)
        self.assertEqual(sorted(got), ["b/small1.java", "b/small2.java"])

    def test_priority_는_몫보다_먼저다(self):
        """이 PR 이 건드린 파일은 어느 글롭의 몫과도 무관하게 먼저 실린다."""
        self._write("a/1.java", "x" * 80)
        self._write("b/2.java", "y" * 80)
        got, _, _ = self.read(["a/*.java", "b/*.java"],
                              limit_bytes=100, priority=["b/2.java"])
        self.assertIn("b/2.java", got)
        self.assertNotIn("a/1.java", got)

    # --- slicer -----------------------------------------------------------

    def test_몫이_모자라면_자른다(self):
        big = "package p;\n\nclass A {\n" + "".join(
            f"    void m{i}() {{\n" + "        int x = 1;\n" * 8 + "    }\n"
            for i in range(6)) + "}\n"
        self._write("A.java", big)
        got, _, failed = self.read(["*.java"], limit_bytes=len(big) - 1,
                                   slicer=run.slice_anchor)
        self.assertEqual(failed, [])
        self.assertIn("본문 생략", got["A.java"])
        self.assertIn("앵커 예산이 모자라", got["A.java"])

    def test_몫이_넉넉하면_원본을_싣는다(self):
        """작은 PR 은 품질이 떨어지지 않아야 한다."""
        big = "package p;\n\nclass A {\n    void m() {\n        int x = 1;\n    }\n}\n"
        self._write("A.java", big)
        got, _, _ = self.read(["*.java"], limit_bytes=10_000, slicer=run.slice_anchor)
        self.assertEqual(got["A.java"], big)
        self.assertNotIn("본문 생략", got["A.java"])

    def test_자를_수_없는_확장자는_그대로_둔다(self):
        sql = "-- c\n" + "SELECT 1;\n" * 50
        self._write("a.sql", sql)
        got, _, failed = self.read(["*.sql"], limit_bytes=len(sql) - 1,
                                   slicer=run.slice_anchor)
        self.assertEqual(got, {})
        self.assertEqual(len(failed), 1)


class FairSharesTest(unittest.TestCase):
    """_fair_shares 는 최대최소 공정 배분이다. 적게 쓰는 쪽이 남긴 몫이 넘어간다."""

    def test_다_들어가면_필요한_만큼_준다(self):
        self.assertEqual(run._fair_shares({"a": 10, "b": 20}, 100), {"a": 10, "b": 20})

    def test_모자라면_같게_나눈다(self):
        got = run._fair_shares({"a": 100, "b": 100}, 100)
        self.assertEqual(got, {"a": 50, "b": 50})

    def test_적게_쓰는_쪽이_남긴_몫이_넘어간다(self):
        """a 가 10 만 쓰므로 b 는 50 이 아니라 90 을 받는다."""
        got = run._fair_shares({"a": 10, "b": 500}, 100)
        self.assertEqual(got, {"a": 10, "b": 90})

    def test_필요가_0_인_글롭은_몫을_안_먹는다(self):
        """다른 글롭이 이미 그 파일을 가져간 경우다."""
        got = run._fair_shares({"a": 0, "b": 100}, 100)
        self.assertEqual(got, {"a": 0, "b": 100})

    def test_예산이_0_이면_아무도_못_받는다(self):
        self.assertEqual(run._fair_shares({"a": 10}, 0), {"a": 0})


class SliceJavaTest(unittest.TestCase):
    """
    slice_java 는 메서드 본문만 지운다.

    남기는 것은 애너테이션, 필드, 시그니처, 중첩 타입이다. 점검 항목의 다수가 그것으로
    판정된다. 지우면 안 되는 것을 지우면 판정 근거가 조용히 사라진다.
    """

    def _src(self, body_lines=80):
        return ("package p;\n\nimport java.util.List;\n\n@Service\n"
                "public class A {\n\n    private final Repo repo;\n\n"
                "    public record R(int a, String b) {\n    }\n\n"
                "    @Transactional\n    public List<R> find(int id) {\n"
                + "        int x = 1;\n" * body_lines +
                "        return null;\n    }\n}\n")

    def test_본문을_지운다(self):
        out, info = run.slice_java(self._src())
        self.assertIsNotNone(info)
        self.assertIn("본문 생략", out)
        self.assertNotIn("int x = 1;", out)

    def test_애너테이션과_필드와_시그니처를_남긴다(self):
        out, _ = run.slice_java(self._src())
        for keep in ("@Service", "@Transactional", "private final Repo repo;",
                     "public List<R> find(int id) {", "import java.util.List;"):
            self.assertIn(keep, out)

    def test_중첩_타입은_건드리지_않는다(self):
        """이 저장소의 DTO 가 record 라 그 안이 깊이 2 다. 지우면 필드가 사라진다."""
        out, _ = run.slice_java(self._src())
        self.assertIn("public record R(int a, String b) {", out)

    def test_괄호_짝이_맞는다(self):
        """닫는 괄호까지 지우면 파일이 안 읽힌다."""
        out, _ = run.slice_java(self._src())
        _, last = run.line_depths(out)
        self.assertEqual(last, 0)

    def test_줄어드는_양이_적으면_원본을_준다(self):
        """잘라서 근거를 잃는 것보다 큰 편이 낫다. slice_ddl 과 같은 태도다."""
        src = self._src(body_lines=0)
        out, info = run.slice_java(src)
        self.assertIsNone(info)
        self.assertEqual(out, src)

    def test_문자열_안의_중괄호를_세지_않는다(self):
        """
        JSON 을 손으로 만드는 코드에 짝이 안 맞는 중괄호 문자열이 흔하다.

        짝이 맞는 "a={}" 로는 이 시험이 아무것도 안 잡는다. 세도 net 0 이라 깊이가 같다.
        여는 쪽만 둘을 둔다. 세는 순간 깊이가 영구히 +2 로 어긋나고, 그러면 slice_java 가
        원본을 돌려주면서 자르기가 조용히 멈춘다. 문자열과 문자 상수를 각각 하나씩 덮는다.
        """
        src = ('package p;\n\nclass A {\n'
               + '    private static final String OPEN = "{";\n'
               + "    private static final char OPEN_CH = '{';\n"
               + '    void m() {\n'
               + '        int x = 1;\n' * 80
               + '    }\n\n    private int keep;\n}\n')
        out, info = run.slice_java(src)
        self.assertIsNotNone(info)
        self.assertIn("private int keep;", out)
        self.assertIn('String OPEN = "{";', out)
        _, last = run.line_depths(out)
        self.assertEqual(last, 0)

    def test_주석_안의_중괄호를_세지_않는다(self):
        src = ('package p;\n\nclass A {\n    /* { { { */\n    void m() {\n'
               + '        int x = 1;\n' * 80 +
               '    }\n\n    private int keep;\n}\n')
        out, info = run.slice_java(src)
        self.assertIsNotNone(info)
        self.assertIn("private int keep;", out)
        _, last = run.line_depths(out)
        self.assertEqual(last, 0)

    def test_깊이가_안_맞으면_원본을_준다(self):
        out, info = run.slice_java("class A { void m() {\n")
        self.assertIsNone(info)



class ExitCodeTest(unittest.TestCase):
    """
    판정하지 못한 항목이 있으면 종료 코드가 1 이다.

    여태 0 이었다. 그래서 판정을 한 건도 못 했는데 체크가 초록이었다. 2026-09-24 에 한도가
    말라 383건 전부 UNJUDGED 로 끝난 회차가 초록이었고 아무도 몇 주 동안 몰랐다.
    2026-09-25 에는 같은 일을 하루에 네 번 봤다.

    보고서는 이미 "통과가 아니다" 라고 적는데 체크만 반대로 말하고 있었다. 사람은 코멘트를
    열기 전에 체크 색을 먼저 본다. 이 시험이 그 둘을 같은 뜻으로 묶어 둔다.

    run.py 의 main 을 통째로 부르는 것은 git 저장소 셋과 판정 엔진이 필요해 여기서 못 한다.
    대신 종료 코드를 정하는 조건을 그대로 복제해 시험한다. 조건이 바뀌면 이 시험이 먼저 깨진다.
    """

    def _exit_code(self, unjudged, stages):
        """run.py 말미의 판단을 그대로 옮긴 것이다."""
        if unjudged:
            return 1
        return 0

    def test_전부_판정하면_0_이다(self):
        self.assertEqual(self._exit_code([], {1: {"error": None}}), 0)

    def test_한_건도_못_판정하면_1_이다(self):
        """2026-09-24 회차다. 383건 전부 미판정인데 초록이었다."""
        self.assertEqual(self._exit_code(["A-1"] * 383, {1: {"error": "한도 초과"}}), 1)

    def test_일부만_못_판정해도_1_이다(self):
        """2026-09-25 의 #138 이다. 235건은 판정됐고 2단계 148건이 죽었는데 초록이었다."""
        self.assertEqual(
            self._exit_code(["A-1"] * 148,
                            {1: {"error": None}, 2: {"error": "일일 한도 소진"}}), 1)

    def test_실제_소스가_이_조건을_쓰는지_확인한다(self):
        """
        위 세 시험은 복제본을 보므로 원본이 바뀌어도 안 깨진다. 그래서 원본을 직접 읽는다.

        continue-on-error 로 다시 덮이거나 return 0 으로 되돌아가는 것을 막는 자리다.
        """
        src = (HERE / "run.py").read_text(encoding="utf-8")
        self.assertIn("if unjudged:", src)
        self.assertRegex(src, r"if unjudged:(?:.|\n)*?return 1")

    def test_워크플로가_판정_실패를_삼키지_않는다(self):
        """
        continue-on-error 가 붙으면 run.py 가 1 로 끝내도 체크가 초록이 된다.

        낱말로 찾지 않고 YAML 키로 본다. 이 워크플로의 주석에 "continue-on-error 를 붙이지
        않는다" 라고 적혀 있어서, 낱말로 찾으면 그 주석이 잡힌다.
        """
        wf = HERE.parent / "workflows" / "llm-verify.yml"
        if not wf.exists():
            self.skipTest("워크플로를 찾을 수 없다")
        import yaml
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            self.assertNotIn("continue-on-error", job, f"잡 {job_name}")
            for step in (job.get("steps") or []):
                self.assertNotIn("continue-on-error", step,
                                 f"스텝 {step.get('name') or step.get('uses')}")



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
