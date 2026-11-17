import importlib.util
import http.client
import io
import json
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError, URLError

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ppt-review-pilot.py"
spec = importlib.util.spec_from_file_location("ppt_review_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def _input(tmp_path):
    data = json.loads((SCRIPT.parent / "fixtures" / "ppt-review-ocean.json").read_text(encoding="utf-8"))
    data["timeout_seconds"] = 5
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def ready_api(monkeypatch):
    monkeypatch.setattr(pilot, "check_api_ready", lambda *args, **kwargs: None)


def test_unknown_completion_blocks_an_autoloop_retry(tmp_path, monkeypatch, capsys, ready_api):
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


def test_complete_failure_is_recorded_without_scheduler_retry(tmp_path, monkeypatch, ready_api):
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


def test_autoloop_receipt_is_utf8_with_a_windows_cp1252_stdout(tmp_path, monkeypatch, ready_api):
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
def test_failed_receipt_keeps_lock_and_blocks_second_model_call(tmp_path, monkeypatch, failure_phase, ready_api):
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


def test_truncated_http_response_keeps_lock_and_blocks_second_post(tmp_path, monkeypatch, ready_api):
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


def test_check_only_reads_existing_route_metadata_and_never_posts(tmp_path, monkeypatch, capsys):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output), "--check-only"])
    requests = []

    class Opener:
        def open(self, req, *, timeout):
            requests.append(req)
            return io.BytesIO(json.dumps({"paths": {pilot.REVIEW_PATH: {"post": {}}}}).encode())

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(AssertionError("must not post")))
    assert pilot.main() == 0
    assert len(requests) == 1
    assert requests[0].get_method() == "GET"
    assert requests[0].full_url.endswith("/openapi.json")
    assert not output.exists()
    assert "模型配置与模型响应尚未验证" in capsys.readouterr().out


@pytest.mark.parametrize("docs_result", [404, 403, b"<html>Documentation is disabled</html>"])
def test_hidden_openapi_falls_back_to_safe_gets_of_each_needed_route(monkeypatch, docs_result):
    requests = []

    class Opener:
        def open(self, req, *, timeout):
            requests.append(req)
            if req.full_url.endswith("/openapi.json"):
                if isinstance(docs_result, int):
                    raise HTTPError(req.full_url, docs_result, "docs unavailable", {}, None)
                return io.BytesIO(docs_result)
            raise HTTPError(req.full_url, 405, "method not allowed", {"Allow": "OPTIONS, POST"}, None)

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    pilot.check_api_ready("http://127.0.0.1:8000", needs_generation=True)
    assert [req.full_url for req in requests] == [
        "http://127.0.0.1:8000/openapi.json",
        "http://127.0.0.1:8000" + pilot.REVIEW_PATH,
        "http://127.0.0.1:8000" + pilot.GENERATION_PATH,
    ]
    assert all(req.get_method() == "GET" and req.data is None for req in requests)


@pytest.mark.parametrize("status,allow", [(401, "POST"), (403, "POST"), (503, "POST"), (405, "GET"), (200, "POST")])
def test_route_fallback_requires_405_with_post_and_preserves_auth_errors(monkeypatch, status, allow):
    requests = []

    class Opener:
        def open(self, req, *, timeout):
            requests.append(req)
            if req.full_url.endswith("/openapi.json"):
                raise HTTPError(req.full_url, 404, "docs disabled", {}, None)
            if status != 200:
                raise HTTPError(req.full_url, status, "route response", {"Allow": allow}, None)
            response = io.BytesIO(b"OK")
            response.status, response.headers = status, {"Allow": allow}
            return response

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    with pytest.raises(pilot.PilotError) as caught:
        pilot.check_api_ready("http://127.0.0.1:8000")
    assert len(requests) == 2
    assert all(req.get_method() == "GET" for req in requests)
    if status in {401, 403}:
        assert "需要认证" in str(caught.value)
    else:
        assert f"HTTP {status}" in str(caught.value)


@pytest.mark.parametrize("status", [401, 503])
def test_openapi_auth_or_service_failure_does_not_blindly_probe_more_routes(monkeypatch, status):
    requests = []

    class Opener:
        def open(self, req, *, timeout):
            requests.append(req)
            raise HTTPError(req.full_url, status, "unavailable", {}, None)

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    with pytest.raises(pilot.PilotError):
        pilot.check_api_ready("http://127.0.0.1:8000")
    assert len(requests) == 1


@pytest.mark.parametrize("unavailable", ["offline", "old_backend"])
def test_preflight_failure_stops_before_post_without_leaving_unknown_lock(tmp_path, monkeypatch, unavailable):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])

    class Opener:
        def open(self, req, *, timeout):
            if unavailable == "offline":
                raise URLError(ConnectionRefusedError())
            return io.BytesIO(b'{"paths": {}}')

    monkeypatch.setattr(pilot.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(AssertionError("must not post")))
    assert pilot.main() == 2
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "client_error"
    assert report["completion_unknown"] is False
    assert not (output / "autoloop-inflight.json").exists()


@pytest.mark.parametrize("field,value", [("timeout_seconds", None), ("max_revision_rounds", 3)])
def test_invalid_parameters_get_a_readable_report_before_network(tmp_path, monkeypatch, field, value):
    path = _input(tmp_path)
    body = json.loads(path.read_text())
    body[field] = value
    path.write_text(json.dumps(body))
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])
    monkeypatch.setattr(pilot, "check_api_ready", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not connect")))
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(AssertionError("must not post")))
    assert pilot.main() == 2
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "client_error"
    assert field in report["message"]
    assert report["completion_unknown"] is False


@pytest.mark.parametrize("autoloop", [False, True])
def test_ctrl_c_records_unknown_remote_result_and_blocks_a_repeat(tmp_path, monkeypatch, ready_api, autoloop):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    argv = [str(SCRIPT), "--input", str(path), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", argv + (["--autoloop"] if autoloop else []))
    calls = []

    def interrupted(*args):
        calls.append(args)
        raise KeyboardInterrupt()

    monkeypatch.setattr(pilot, "post_json", interrupted)
    assert pilot.main() == (0 if autoloop else 130)
    assert (output / "autoloop-inflight.json").exists()
    report = json.loads(next(output.glob("*/review.json")).read_text())
    assert report["status"] == "cancelled"
    assert report["completion_unknown"] is True
    assert "本地等待" in report["message"]
    assert pilot.main() == (0 if autoloop else 2)
    assert len(calls) == 1
    assert not any(t.name == "ppt-review-progress" for t in threading.enumerate())


def test_waiting_feedback_stops_its_thread_after_exception(monkeypatch, capsys):
    monkeypatch.setattr(pilot, "WAIT_NOTICE_SECONDS", 0.01)
    with pytest.raises(RuntimeError):
        with pilot.waiting_for("测试阶段", 5):
            threading.Event().wait(0.05)
            raise RuntimeError("done")
    output = capsys.readouterr().err
    assert "正在提交并等待结果" in output
    assert "已等待" in output
    assert not any(t.name == "ppt-review-progress" for t in threading.enumerate())


def test_simultaneous_direct_runs_share_the_existing_inflight_lock(tmp_path, monkeypatch, ready_api):
    path = _input(tmp_path)
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []

    def delayed(*args):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return {"status": "passed", "original_plan": {"slides": []}, "plan": {"slides": []},
                "visual_validation": "not_performed"}

    monkeypatch.setattr(pilot, "post_json", delayed)
    first = threading.Thread(target=lambda: results.append(pilot.main()))
    first.start()
    try:
        assert entered.wait(2)
        assert pilot.main() == 2
        assert len(calls) == 1
        assert (output / "autoloop-inflight.json").exists()
    finally:
        release.set()
        first.join(2)
    assert not first.is_alive()
    assert results == [0]
    assert not (output / "autoloop-inflight.json").exists()


def test_bad_input_is_reported_without_sending_request(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(AssertionError("must not call")))
    assert pilot.main() == 2
    assert next(output.glob("*/comparison.html")).exists()


def test_schema_rejected_slide_still_produces_a_readable_failure_report(tmp_path, monkeypatch, ready_api):
    path = _input(tmp_path)
    body = json.loads(path.read_text())
    body["plan"]["slides"][0].update(screen_content=None, assets=None, interaction=None)
    path.write_text(json.dumps(body))
    output = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(path), "--output", str(output)])
    monkeypatch.setattr(pilot, "post_json", lambda *args: (_ for _ in ()).throw(pilot.PilotError("HTTP 422 输入格式不符")))
    assert pilot.main() == 2
    assert "HTTP 422" in next(output.glob("*/comparison.html")).read_text(encoding="utf-8")
    assert not (output / "autoloop-inflight.json").exists()


def test_report_escapes_model_text_and_does_not_claim_visual_acceptance():
    report = {"status": "passed", "message": '<script>alert("x")</script>',
              "original_plan": {"slides": []}, "plan": {"slides": []}}
    rendered = pilot.render_report(report, {"topic": '<img src=x onerror="alert(1)">'})
    assert "<script>" not in rendered
    assert "<img src=x" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "不代表教师验收或图片、排版合格" in rendered
