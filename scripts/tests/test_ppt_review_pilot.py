import importlib.util
import http.client
import io
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ppt-review-pilot.py"
spec = importlib.util.spec_from_file_location("ppt_review_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def _input(tmp_path):
    data = {"brief": {"topic": "海洋动物"}, "plan": {"slides": []}, "timeout_seconds": 5}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_unknown_completion_blocks_an_autoloop_retry(tmp_path, monkeypatch, capsys):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--autoloop"])
    calls = []

    def fail(*args):
        calls.append(args)
        raise pilot.PilotError("Completion unknown", uncertain=True)

    monkeypatch.setattr(pilot, "post_json", fail)
    assert pilot.main() == 0
    assert (output / "autoloop-inflight.json").exists()
    assert pilot.main() == 0
    assert len(calls) == 1
    reports = [json.loads(p.read_text()) for p in output.glob("*/review.json")]
    assert len(reports) == 2
    assert all(r["status"] == "client_error" for r in reports)
    assert all(r["call_attempts"] is None for r in reports)
    assert "```agent-autoloop" in capsys.readouterr().out


def test_complete_failure_is_recorded_without_scheduler_retry(tmp_path, monkeypatch):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--autoloop"])
    result = {"status": "model_error", "message": "模型调用失败", "original_plan": {"slides": []},
              "plan": {"slides": []}, "visual_validation": "not_performed", "call_attempts": 1,
              "calls": [], "review_history": []}
    monkeypatch.setattr(pilot, "post_json", lambda *args: result)
    assert pilot.main() == 0
    assert not (output / "autoloop-inflight.json").exists()
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "model_error"
    assert not list(output.glob("*/reviewed-plan.json"))


def test_autoloop_receipt_is_utf8_with_a_windows_cp1252_stdout(tmp_path, monkeypatch):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--autoloop"])
    result = {"status": "model_error", "message": "模型调用失败", "original_plan": {"slides": []},
              "plan": {"slides": []}, "visual_validation": "not_performed"}
    monkeypatch.setattr(pilot, "post_json", lambda *args: result)
    raw_output = io.BytesIO()
    stream = io.TextIOWrapper(raw_output, encoding="cp1252")
    with monkeypatch.context() as output_patch:
        output_patch.setattr(sys, "stdout", stream)
        assert pilot.main() == 0
    receipt_text = raw_output.getvalue().decode("utf-8")
    assert "模型调用失败" in receipt_text
    assert "```agent-autoloop" in receipt_text
    assert not (output / "autoloop-inflight.json").exists()


@pytest.mark.parametrize("failure_phase", ["write", "flush"])
def test_failed_receipt_keeps_lock_and_blocks_second_model_call(tmp_path, monkeypatch, failure_phase):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--autoloop"])
    calls = []

    def completed(*args):
        calls.append(args)
        return {"status": "passed", "original_plan": {"slides": []}, "plan": {"slides": []},
                "visual_validation": "not_performed"}

    class FailedReceipt(io.StringIO):
        def write(self, value):
            if failure_phase == "write" and "```agent-autoloop" in value:
                raise BrokenPipeError("receipt output closed")
            return super().write(value)

        def flush(self):
            if failure_phase == "flush":
                raise BrokenPipeError("receipt output closed")
            return super().flush()

    monkeypatch.setattr(pilot, "post_json", completed)
    with monkeypatch.context() as output_patch:
        output_patch.setattr(sys, "stdout", FailedReceipt())
        with pytest.raises(BrokenPipeError):
            pilot.main()
    assert (output / "autoloop-inflight.json").exists()
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "passed"
    assert pilot.main() == 0
    assert len(calls) == 1
    assert (output / "autoloop-inflight.json").exists()


def test_truncated_http_response_keeps_lock_and_blocks_second_post(tmp_path, monkeypatch):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--autoloop"])
    calls = []

    class TruncatedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, amount):
            raise http.client.IncompleteRead(b'{"status":', 100)

    class Opener:
        def open(self, req, *, timeout):
            calls.append(req)
            return TruncatedResponse()

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    assert pilot.main() == 0
    assert (output / "autoloop-inflight.json").exists()
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "client_error"
    assert report["completion_unknown"] is True
    assert pilot.main() == 0
    assert len(calls) == 1


def test_bad_input_is_reported_without_sending_request(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(AssertionError("must not call")))
    assert pilot.main() == 2
    assert next(output.glob("*/comparison.html")).exists()


def test_report_escapes_model_text_and_does_not_claim_visual_acceptance():
    report = {"status": "passed", "message": '<script>alert("x")</script>',
              "original_plan": {"slides": []}, "plan": {"slides": []}}
    rendered = pilot.render_report(report, {"topic": '<img src=x onerror="alert(1)">'})
    assert "<script>" not in rendered
    assert "<img src=x" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "不代表教师验收或图片、排版合格" in rendered
