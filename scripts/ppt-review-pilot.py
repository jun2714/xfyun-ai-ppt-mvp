#!/usr/bin/env python3
"""Run an explicit text-review experiment against a local PPT API.

Standard library only. This client never loads provider keys or .env files. It
does not save a presentation, generate images, publish content, or retry a POST.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import http.client
import json
import os
from pathlib import Path
import sys
import time
from urllib import error, request
from urllib.parse import urlsplit
import uuid


STATUSES = {
    "passed": "文稿审核通过", "needs_revision": "仍需修改", "needs_human": "需要确认",
    "max_rounds_reached": "达到修订上限", "no_progress": "未继续改善",
    "budget_exhausted": "达到调用上限", "timeout": "审核超时", "cancelled": "审核已取消",
    "model_error": "模型调用失败", "invalid_output": "模型输出不符合要求",
    "revision_rejected": "修订未被采用", "client_error": "本机调用未完成",
}


class PilotError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(base: str, path: str, payload: dict, timeout: float) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.getenv("PPT_REVIEW_BEARER_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(base.rstrip("/") + path,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers=headers, method="POST")
    try:
        with request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise PilotError("API response exceeds the experiment limit.", uncertain=True)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected JSON object")
        return result
    except error.HTTPError as exc:
        # Do not print arbitrary proxy/provider bodies, which may contain secrets.
        raise PilotError(f"PPT API returned HTTP {exc.code}; inspect the local API log.",
                         uncertain=exc.code >= 500) from exc
    except (error.URLError, OSError, http.client.HTTPException) as exc:
        raise PilotError("PPT API connection interrupted or timed out; completion is unknown. "
                         "Check the local API before submitting again.", uncertain=True) from exc
    except (ValueError, UnicodeError) as exc:
        raise PilotError("PPT API did not return a valid JSON object.", uncertain=True) from exc


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _escape(value) -> str:
    return html.escape("未核实" if value is None else str(value), quote=True)


def _slide_text(slide: dict) -> str:
    screen = slide.get("screen_content", {})
    points = "".join(f"<li>{_escape(point)}</li>" for point in screen.get("points", []))
    assets = "".join(
        f"<li><b>{_escape(asset.get('semantic_label', ''))}</b>：{_escape(asset.get('description', ''))}</li>"
        for asset in slide.get("assets", [])
    )
    return (f"<h3>{_escape(screen.get('title', ''))}</h3><ul>{points}</ul>"
            f"<p><b>幼儿指令：</b>{_escape(screen.get('instruction') or '')}</p>"
            f"<p><b>教学目标：</b>{_escape(slide.get('teaching_goal', ''))}</p>"
            f"<p><b>互动：</b>{_escape(slide.get('interaction', {}).get('instruction') or '')}</p>"
            f"<details><summary>教师备注与配图要求</summary><p>{_escape(slide.get('teacher_note', ''))}</p>"
            f"<ul>{assets}</ul></details>")


def render_report(report: dict, brief: dict) -> str:
    status = report.get("status", "client_error")
    original = report.get("original_plan", {}).get("slides", [])
    final = {slide.get("slide_no"): slide for slide in report.get("plan", {}).get("slides", [])}
    rows = []
    for slide in original:
        revised = final.get(slide.get("slide_no"), slide)
        changed = slide != revised
        rows.append(f"<section class='slide'><div class='page'>第 {_escape(slide.get('slide_no'))} 页 · "
                    f"{'已修改' if changed else '保留原稿'}</div><div class='columns'>"
                    f"<article><small>原稿</small>{_slide_text(slide)}</article>"
                    f"<article><small>当前采用稿</small>{_slide_text(revised)}</article></div></section>")
    history = []
    for snapshot in report.get("review_history", []):
        findings = snapshot.get("semantic_review", {}).get("findings", [])
        items = "".join(
            f"<li><b>第 {_escape(item.get('slide_no'))} 页 · {_escape(item.get('criterion'))}</b>"
            f"<p>原文：{_escape(item.get('evidence'))}</p><p>问题：{_escape(item.get('explanation'))}</p>"
            f"<p>依据：{_escape(item.get('requirement'))}</p><p>建议：{_escape(item.get('suggestion'))}</p></li>"
            for item in findings
        )
        review = snapshot.get("semantic_review", {})
        questions = "".join(f"<li>{_escape(item)}</li>" for item in review.get("human_questions", []))
        history.append(f"<details open><summary>第 {_escape(snapshot.get('round_no'))} 轮审核 · "
                       f"{len(findings)} 条语义意见 · {'采用' if snapshot.get('adopted') else '未采用'}</summary>"
                       f"<p>参考资料状态：{_escape(review.get('source_status'))}</p>"
                       f"<ol>{items}</ol><ul>{questions}</ul></details>")
    calls = report.get("calls", [])
    call_rows = "".join(
        "<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in [
            call.get("attempt"), call.get("stage"), call.get("outcome"), call.get("model") or "未知",
            call.get("elapsed_ms"), (call.get("usage") or {}).get("total_tokens") if
            (call.get("usage") or {}).get("total_tokens") is not None else "未上报",
        ]) + "</tr>" for call in calls
    )
    machine = report.get("machine_quality", {})
    machine_items = "".join(f"<li>{_escape(item.get('message', ''))}</li>"
                            for item in machine.get("errors", []) + machine.get("warnings", []))
    semantic = report.get("semantic_review") or {}
    human_items = "".join(f"<li>{_escape(value)}</li>" for value in semantic.get("human_questions", []))
    limits = report.get("limitations", []) or ["本次仅处理文稿，未检查实际图片像素、PPT排版或导出。"]
    limit_items = "".join(f"<li>{_escape(value)}</li>" for value in limits)
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PPT 文稿审核对比</title><style>
body{margin:0;background:#f6f7f9;color:#17212b;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1160px;margin:auto;padding:28px}h1{font-size:28px}h2{font-size:21px;margin-top:32px}
.status{border-left:5px solid #246b91;padding:16px;background:#eaf3f8}.status p{margin:6px 0}
.slide,details{background:white;border:1px solid #dfe3e8;margin:14px 0}.page{padding:10px 16px;background:#eaf0f5;font-weight:600}
.columns{display:grid;grid-template-columns:1fr 1fr}article{padding:16px;min-width:0}article+article{border-left:1px solid #dfe3e8}
small{color:#64748b}h3{margin:8px 0}p,li{overflow-wrap:anywhere;white-space:pre-wrap}details{padding:12px}summary{cursor:pointer;font-weight:600}
table{width:100%;border-collapse:collapse;background:white}td,th{border:1px solid #dfe3e8;padding:8px;text-align:left}
@media(max-width:720px){main{padding:16px}.columns{grid-template-columns:1fr}article+article{border-left:0;border-top:1px solid #dfe3e8}}
@media print{details{display:block}.slide{break-inside:avoid}main{padding:0}}
</style><main>""" + (
        f"<h1>PPT 文稿审核对比</h1><p>{_escape(brief.get('topic', ''))} · "
        f"{_escape(brief.get('age_group', ''))}</p><div class='status'><b>{_escape(STATUSES.get(status, status))}</b>"
        f"<p>{_escape(report.get('message', ''))}</p><p>已完成修订复审轮数：{_escape(report.get('rounds_completed', 0))} · "
        f"模型调用尝试：{_escape(report.get('call_attempts', 0))} · 审核耗时：{_escape(report.get('elapsed_ms', 0))} ms</p>"
        "<p>“文稿审核通过”仅指本次检查完成，不代表教师验收或图片、排版合格。</p></div>"
        f"<h2>本次要求</h2><p>{_escape(brief.get('instructions') or '')}</p>"
        f"<details><summary>来源与参考资料</summary><p>{_escape(brief.get('source_context') or '未提供参考资料')}</p></details>"
        f"<h2>程序检查与待确认项</h2><ul>{machine_items}{human_items}</ul>"
        f"<h2>审核记录</h2>{''.join(history) or '<p>本次没有完成语义审核。</p>'}"
        f"<h2>逐页对比</h2>{''.join(rows)}<h2>调用记录</h2><table>"
        "<tr><th>尝试</th><th>阶段</th><th>结果</th><th>模型</th><th>耗时 ms</th><th>总 Token</th></tr>"
        f"{call_rows}</table><h2>验证范围</h2><ul>{limit_items}</ul></main></html>"
    )


def _arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Existing review request JSON")
    source.add_argument("--topic", help="Generate a fresh lesson through the existing local API first")
    parser.add_argument("--output", type=Path, default=Path(".data/ppt-review"))
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--age-group", default="4-5岁")
    parser.add_argument("--domain", default="science")
    parser.add_argument("--content-mode", choices=["classroom", "training"], default="classroom")
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--slides", type=int, default=8)
    parser.add_argument("--instructions", default="围绕一个核心教学目标，提供可执行的幼儿活动与教师引导。")
    parser.add_argument("--max-revisions", type=int, choices=[0, 1, 2])
    parser.add_argument("--timeout", type=float, help="Review budget in seconds, at most 600")
    parser.add_argument("--autoloop", action="store_true", help="Finish one scheduler round even on a recorded failure")
    return parser.parse_args()


def main() -> int:
    # Autoloop captures stdout in a file. On Windows that otherwise uses the
    # local code page, which may reject Chinese or corrupt the UTF-8 receipt.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    args = _arguments()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = args.output / run_id
    folder.mkdir()
    lock = args.output / "autoloop-inflight.json"
    owns_lock, uncertain = False, False
    brief: dict = {}
    body: dict = {}
    report: dict = {}
    started = time.monotonic()
    try:
        parsed = urlsplit(args.api_base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise PilotError("Invalid --api-base; supply the local API origin or proxy prefix.")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise PilotError("Non-local APIs must use HTTPS.")
        if args.input:
            if args.input.stat().st_size > 2_000_000:
                raise PilotError("Review input exceeds 2 MB.")
            body = json.loads(args.input.read_text(encoding="utf-8-sig"))
            if not isinstance(body, dict) or not isinstance(body.get("brief"), dict) or not isinstance(body.get("plan"), dict):
                raise PilotError("Input must contain brief and plan objects.")
            brief = body["brief"]
        else:
            brief = {"topic": args.topic, "age_group": args.age_group, "domain": args.domain,
                     "content_mode": args.content_mode, "duration_minutes": args.duration,
                     "n_slides": args.slides, "instructions": args.instructions}
            body = {"brief": brief, "max_revision_rounds": 2, "timeout_seconds": 360, "max_model_calls": 5}
        if args.max_revisions is not None:
            body["max_revision_rounds"] = args.max_revisions
        if args.timeout is not None:
            body["timeout_seconds"] = args.timeout
        budget = float(body.get("timeout_seconds", 120))
        if not 1 <= budget <= 600:
            raise PilotError("Review timeout must be between 1 and 600 seconds.")
        if args.autoloop:
            try:
                with lock.open("x", encoding="utf-8") as handle:
                    json.dump({"run_id": run_id, "report_directory": str(folder), "pid": os.getpid()}, handle)
                owns_lock = True
            except FileExistsError as exc:
                raise PilotError("An earlier autoloop request is active or its completion is unknown. "
                                 "Inspect autoloop-inflight.json and local API status before removing the lock.") from exc
        if not args.input:
            write_json(folder / "generation-request.json", brief)
            generated = post_json(args.api_base, "/api/v1/ppt/kindergarten/lesson-plan", brief, 660)
            if not isinstance(generated.get("plan"), dict):
                raise PilotError("The generation API returned no lesson plan.")
            body["plan"] = generated["plan"]
            write_json(folder / "generation-response.json", generated)
        write_json(folder / "request.json", body)
        write_json(folder / "original-plan.json", body["plan"])
        report = post_json(args.api_base, "/api/v1/ppt/kindergarten/lesson-plan/review", body, budget + 30)
        if (report.get("status") not in STATUSES or not isinstance(report.get("plan"), dict)
                or not isinstance(report.get("original_plan"), dict)
                or report.get("visual_validation") != "not_performed"):
            raise PilotError("Review API returned an incompatible response.", uncertain=True)
        # Only a completed, adopted review snapshot establishes which copy was
        # actually reviewed. Failed candidate revisions are not called final.
        if report.get("review_history"):
            write_json(folder / "reviewed-plan.json", report["plan"])
    except (PilotError, OSError, ValueError) as exc:
        uncertain = isinstance(exc, PilotError) and exc.uncertain
        input_plan = body.get("plan", {}) if isinstance(body, dict) else {}
        original = report.get("original_plan", input_plan)
        report = {"status": "client_error", "message": str(exc), "original_plan": original,
                  "plan": original, "rounds_completed": 0, "call_attempts": None, "calls": [],
                  "elapsed_ms": int((time.monotonic() - started) * 1000),
                  "visual_validation": "not_performed", "completion_unknown": uncertain,
                  "limitations": ["API 调用未完成，不能据此评价审核效果。", "未检查实际图片、PPT排版或导出。"]}
    finally:
        write_json(folder / "review.json", report)
        (folder / "comparison.html").write_text(render_report(report, brief), encoding="utf-8")
    label = STATUSES.get(report.get("status"), "未完成")
    print(f"PPT 审核试验结束：{label}。报告：{folder}")
    if args.autoloop:
        receipt = {"notice": [{"title": "PPT 文稿审核：" + label,
                               "text": f"状态：{report.get('status')}。报告目录：{folder}。"
                                       "本次未生成图片或检查PPT排版。",
                               "key": "ppt-review-" + run_id, "fyi": True}]}
        print("```agent-autoloop\n" + json.dumps(receipt, ensure_ascii=False) + "\n```")
    # Keep the lock if writing/flushing the receipt fails. Otherwise the worker
    # could retry a charged request after seeing a nonzero process exit.
    sys.stdout.flush()
    if owns_lock and not uncertain:
        lock.unlink(missing_ok=True)
    if args.autoloop:
        # A failed assessment still completes this scheduler round. Returning a
        # failure exit code would cause autoloop to repeat potentially paid work.
        return 0
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
