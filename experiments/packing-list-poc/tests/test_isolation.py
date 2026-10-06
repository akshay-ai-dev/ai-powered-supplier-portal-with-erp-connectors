"""Process-isolation tests: fake workers stand in for Docling so crashes, hangs and retries
can be simulated in a few seconds.

    .venv\\Scripts\\python.exe -m unittest tests.test_isolation -v
"""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evaluate  # noqa: E402
from isolation import (  # noqa: E402
    convert_isolated, describe_exit, is_conversion_error, write_json_atomic,
)

GOOD_RESULT = {"sourceFile": "fake.pdf", "shipDate": "2024-01-16", "carrier": "UPS", "trackingNumbers": ["1Z1"],
               "shippedQuantity": 42.0, "unitOfMeasure": "PR", "lotNumbers": ["2401"], "serialNumbers": [],
               "items": [], "fieldIssues": [], "document": {"pageCount": 1},
               "timings": {"conversionSeconds": 0.1, "extractionSeconds": 0.0, "totalSeconds": 0.1}}

# Behaviours a fake worker can show. Each receives: <pdf> <payload> <state-dir>.
WORKER = textwrap.dedent(r'''
    import json, os, sys, time
    mode, pdf, payload, state = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    counter = os.path.join(state, "calls")
    n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
    open(counter, "w").write(str(n))
    good = json.loads(os.environ["FAKE_RESULT"])

    def crash():
        sys.stderr.write("Windows fatal exception: access violation\n  password=hunter2\n")
        sys.stderr.flush()
        if os.name == "nt":
            os._exit(-1073741819)          # 0xC0000005, what docling-parse produced
        import signal; os.kill(os.getpid(), signal.SIGSEGV)

    def succeed():
        with open(payload, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "result": good, "markdown": "# md"}, f)
        sys.exit(0)

    if mode == "crash":
        crash()
    elif mode == "hang":
        time.sleep(120)
    elif mode == "crash_then_ok":
        crash() if n == 1 else succeed()
    elif mode == "hang_then_ok":
        time.sleep(120) if n == 1 else succeed()
    elif mode == "ok":
        succeed()
    elif mode == "payload_then_crash":   # wrote a valid-looking payload but did not exit cleanly
        with open(payload, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "result": good}, f)
        crash()
    elif mode == "exit0_no_payload":
        sys.exit(0)
    elif mode == "python_error":
        with open(payload, "w", encoding="utf-8") as f:
            json.dump({"ok": False, "error": {"type": "ValueError", "message": "bad PDF"}}, f)
        sys.exit(0)
''')


class IsolationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "fake_worker.py"
        self.script.write_text(WORKER, encoding="utf-8")
        os.environ["FAKE_RESULT"] = json.dumps(GOOD_RESULT)
        self.pdf = self.dir / "fake.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake")

    def tearDown(self):
        self.tmp.cleanup()

    def worker(self, mode):
        state = self.dir / f"state-{mode}"
        state.mkdir(exist_ok=True)
        return lambda pdf, payload: [sys.executable, str(self.script), mode, str(pdf), str(payload), str(state)]

    def calls(self, mode):
        f = self.dir / f"state-{mode}" / "calls"
        return int(f.read_text()) if f.exists() else 0

    def convert(self, mode, timeout_s=60):
        return convert_isolated(self.pdf, timeout_s=timeout_s, worker_argv=self.worker(mode),
                                log_dir=self.dir / "logs")


class ChildFailures(IsolationTestCase):
    def test_crash_then_successful_retry(self):
        result, md = self.convert("crash_then_ok")
        self.assertFalse(is_conversion_error(result))
        self.assertEqual(self.calls("crash_then_ok"), 2)
        iso = result["timings"].pop("isolation")
        self.assertEqual(result, GOOD_RESULT)  # extraction JSON passes through unchanged
        self.assertEqual(md, "# md")
        self.assertEqual([a["status"] for a in iso["attempts"]], ["crash", "ok"])
        self.assertIn("access violation", iso["attempts"][0]["reason"])
        self.assertIsNotNone(iso["attempts"][0]["seconds"])

    def test_two_crashes_give_explicit_conversion_error(self):
        result, md = self.convert("crash")
        self.assertTrue(is_conversion_error(result))
        self.assertIsNone(md)
        self.assertEqual(self.calls("crash"), 2)
        for key in ("shipDate", "carrier", "trackingNumbers", "shippedQuantity", "unitOfMeasure",
                    "lotNumbers", "serialNumbers", "items"):
            self.assertNotIn(key, result)  # no empty fields that could pass for a real extraction
        err = result["conversionError"]
        self.assertEqual(result["sourceFile"], "fake.pdf")
        self.assertIn("fake.pdf", err["pdf"])
        self.assertEqual([a["status"] for a in err["attempts"]], ["crash", "crash"])
        tail = "\n".join(err["attempts"][0]["stderrTail"])
        self.assertIn("access violation", tail)
        self.assertNotIn("hunter2", tail)  # secrets redacted from captured stderr

    def test_timeout_kills_child_and_retries(self):
        t0 = time.perf_counter()
        result, _ = self.convert("hang_then_ok", timeout_s=3)
        self.assertLess(time.perf_counter() - t0, 60)
        self.assertFalse(is_conversion_error(result))
        attempts = result["timings"]["isolation"]["attempts"]
        self.assertEqual([a["status"] for a in attempts], ["timeout", "ok"])
        self.assertIn("timeout", attempts[0]["reason"])

    def test_two_timeouts_give_conversion_error(self):
        result, _ = self.convert("hang", timeout_s=2)
        self.assertTrue(is_conversion_error(result))
        self.assertEqual([a["status"] for a in result["conversionError"]["attempts"]], ["timeout", "timeout"])

    def test_payload_from_crashed_child_is_not_trusted(self):
        result, _ = self.convert("payload_then_crash")
        self.assertTrue(is_conversion_error(result))

    def test_clean_exit_without_payload_and_python_errors_are_failures(self):
        self.assertEqual(self.convert("exit0_no_payload")[0]["conversionError"]["attempts"][0]["status"], "no_output")
        err = self.convert("python_error")[0]["conversionError"]["attempts"][0]
        self.assertEqual((err["status"], err["reason"]), ("worker_error", "ValueError: bad PDF"))

    def test_first_attempt_success_runs_once(self):
        result, _ = self.convert("ok")
        self.assertEqual(self.calls("ok"), 1)
        self.assertEqual(result["timings"]["isolation"]["attemptCount"], 1)

    def test_exit_code_names(self):
        self.assertIn("access violation", describe_exit(-1073741819))
        self.assertIn("access violation", describe_exit(3221225477))
        self.assertEqual(describe_exit(1), "exit code 1")


class AtomicWrites(unittest.TestCase):
    def test_failed_write_leaves_previous_file_intact_and_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out.json"
            write_json_atomic(target, {"a": 1})
            with self.assertRaises(TypeError):
                write_json_atomic(target, {"bad": object()})  # not serialisable
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["out.json"])


class EvaluationContinues(IsolationTestCase):
    def test_failed_pdf_does_not_stop_the_batch(self):
        pdfs = [self.dir / "pdf-1.pdf", self.dir / "pdf-2.pdf", self.dir / "pdf-3.pdf"]
        for p in pdfs:
            p.write_bytes(b"%PDF fake")
        modes = {"pdf-1": "ok", "pdf-2": "crash", "pdf-3": "crash_then_ok"}
        out = self.dir / "out"
        stale = out / "extractions" / "pdf-2.json"
        stale.parent.mkdir(parents=True)
        stale.write_text('{"old": "success from an earlier run"}', encoding="utf-8")

        def convert(pdf):
            return convert_isolated(pdf, timeout_s=60, worker_argv=self.worker(modes[pdf.stem]),
                                    log_dir=out / "logs")

        report = evaluate.run_evaluation(pdfs, self.dir / "no-expected", out, convert=convert)
        self.assertEqual([d["status"] for d in report["documents"]], ["converted", "conversion_error", "converted"])
        self.assertEqual([e["sourceFile"] for e in report["conversionErrors"]], ["pdf-2.pdf"])
        self.assertTrue((out / "extractions" / "pdf-1.json").exists())
        self.assertTrue((out / "extractions" / "pdf-3.json").exists())
        self.assertFalse(stale.exists())  # stale success removed so it cannot be mistaken for this run
        err = json.loads((out / "extractions" / "pdf-2.conversion-error.json").read_text(encoding="utf-8"))
        self.assertEqual(err["status"], "conversion_error")
        self.assertTrue((out / "evaluation_report.json").exists())


if __name__ == "__main__":
    unittest.main()
