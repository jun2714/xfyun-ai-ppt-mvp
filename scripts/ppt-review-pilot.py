#!/usr/bin/env python3
"""Run an explicit text-review experiment against a local PPT API.

Standard library only. This client never loads provider keys or .env files. It
does not save a presentation, generate images, publish content, or retry a POST.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import html
import http.client
import json
import os
from pathlib import Path
import sys
import threading
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
REVIEW_PATH = "/api/v1/ppt/kindergarten/lesson-plan/review"
GENERATION_PATH = "/api/v1/ppt/kindergarten/lesson-plan"
WAIT_NOTICE_SECONDS = 15


class PilotError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_headers() -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.getenv("PPT_REVIEW_BEARER_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def check_post_routes(base: str, paths: list[str]) -> None:
    """Probe a POST route without running it when docs are unavailable."""
    for path in paths:
        req = request.Request(base.rstrip("/") + path, headers=api_headers(), method="GET")
        try:
            with request.build_opener(NoRedirect).open(req, timeout=5) as response:
                status, headers = response.status, response.headers
        except error.HTTPError as exc:
            status, headers = exc.code, exc.headers
            exc.close()
        except (error.URLError, OSError, http.client.HTTPException) as exc:
            raise PilotError(f"无法预检 PPT 接口 {path}。请检查后端连接；本次未提交模型请求。") from exc
        allowed = {method.strip().upper() for method in (headers.get("Allow", "") if headers else "").split(",")}
        if status == 405 and "POST" in allowed:
            continue
        if status in {401, 403}:
            raise PilotError("API 预检需要认证。请在运行终端配置 PPT_REVIEW_BEARER_TOKEN 后重试。")
        raise PilotError(f"API 路由预检返回 HTTP {status}，尚不能确认 {path} 可接受 POST。"
                         "请核对后端地址、版本与启动状态；本次未提交模型请求。")


def check_api_ready(base: str, *, needs_generation: bool = False) -> None:
    """Check existing route metadata with a GET; never invoke a model."""
    req = request.Request(base.rstrip("/") + "/openapi.json", headers=api_headers(), method="GET")
    required = [REVIEW_PATH, GENERATION_PATH] if needs_generation else [REVIEW_PATH]
    try:
        with request.build_opener(NoRedirect).open(req, timeout=5) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("OpenAPI response too large")
        schema = json.loads(raw)
        paths = schema.get("paths") if isinstance(schema, dict) else None
        if not isinstance(paths, dict):
            raise ValueError("Response is not an OpenAPI document")
        if any(
            not isinstance(paths.get(path), dict) or "post" not in paths[path] for path in required
        ):
            raise PilotError("后端尚未提供本次需要的接口。请更新代码并重启 PPT API，然后重新预检。")
    except error.HTTPError as exc:
        if exc.code in {403, 404}:
            exc.close()
            check_post_routes(base, required)
            return
        if exc.code in {401, 403}:
            message = "API 预检需要认证。请在运行终端配置 PPT_REVIEW_BEARER_TOKEN 后重试。"
        else:
            message = (f"API 预检返回 HTTP {exc.code}。请核对 --api-base 是否指向 PPT 后端；"
                       "请同时检查后端启动状态。")
        raise PilotError(message) from exc
    except (error.URLError, OSError, http.client.HTTPException) as exc:
        raise PilotError(f"连接不到 PPT 后端：{base}。请先启动后端，再运行同一命令；本次未提交模型请求。") from exc
    except (ValueError, UnicodeError):
        check_post_routes(base, required)


@contextmanager
def waiting_for(stage: str, timeout: float):
    """Report elapsed waiting time only; the synchronous API has no live progress."""
    started = time.monotonic()
    stop = threading.Event()
    print(f"[{stage}] 正在提交并等待结果，客户端最多等待 {timeout:g} 秒。Ctrl+C 可结束本地等待。",
          file=sys.stderr, flush=True)

    def heartbeat():
        while not stop.wait(WAIT_NOTICE_SECONDS):
            try:
                elapsed = int(time.monotonic() - started)
                print(f"[{stage}] 已等待 {elapsed} 秒，仍在等待后端返回；请勿重复启动。",
                      file=sys.stderr, flush=True)
            except (OSError, ValueError):
                return

    worker = threading.Thread(target=heartbeat, name="ppt-review-progress", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()


def post_json(base: str, path: str, payload: dict, timeout: float) -> dict:
    req = request.Request(base.rstrip("/") + path,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers=api_headers(), method="POST")
    try:
        with request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise PilotError("API 返回内容超过试验上限，请核对后端结果后再运行。", uncertain=True)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected JSON object")
        return result
    except error.HTTPError as exc:
        # Do not print arbitrary proxy/provider bodies, which may contain secrets.
        hint = {401: "请检查当前终端的 PPT_REVIEW_BEARER_TOKEN。",
                403: "当前认证信息无权调用此接口，请检查本机登录或 Token。",
                404: "请更新并重启包含审核接口的 PPT 后端。",
                422: "输入未通过后端格式校验，请核对完整教案及字段类型。"}.get(
                    exc.code, "请查看本机 API 日志，核对本次请求是否已经完成。")
        raise PilotError(f"PPT API 返回 HTTP {exc.code}。{hint}", uncertain=exc.code >= 500) from exc
    except (error.URLError, OSError, http.client.HTTPException) as exc:
        raise PilotError("PPT API 连接中断或等待超时，远端是否完成尚不明确。"
                         "请核对后端任务和本次报告后再开始下一单；不会自动重发。", uncertain=True) from exc
    except (ValueError, UnicodeError) as exc:
        raise PilotError("PPT API 未返回有效 JSON，远端结果尚不明确。请核对后端任务后再开始下一单。",
                         uncertain=True) from exc


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _escape(value) -> str:
    return html.escape("未核实" if value is None else str(value), quote=True)


def _slide_text(slide: dict) -> str:
    # A schema-rejected input still needs a readable failure report.
    screen = slide.get("screen_content")
    screen = screen if isinstance(screen, dict) else {}
    point_values = screen.get("points")
    point_values = point_values if isinstance(point_values, list) else []
    asset_values = slide.get("assets")
    asset_values = asset_values if isinstance(asset_values, list) else []
    interaction = slide.get("interaction")
    interaction = interaction if isinstance(interaction, dict) else {}
    points = "".join(f"<li>{_escape(point)}</li>" for point in point_values)
    assets = "".join(
        f"<li><b>{_escape(asset.get('semantic_label', ''))}</b>：{_escape(asset.get('description', ''))}</li>"
        for asset in asset_values if isinstance(asset, dict)
    )
    return (f"<h3>{_escape(screen.get('title', ''))}</h3><ul>{points}</ul>"
            f"<p><b>幼儿指令：</b>{_escape(screen.get('instruction') or '')}</p>"
            f"<p><b>教学目标：</b>{_escape(slide.get('teaching_goal', ''))}</p>"
            f"<p><b>互动：</b>{_escape(interaction.get('instruction') or '')}</p>"
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
    parser = argparse.ArgumentParser(
        description="显式运行 PPT 文稿审核，保存原稿、审核记录与逐页对比。不会覆盖已保存的 PPT。",
        epilog="先检查而不调用模型：--input 请求文件.json --check-only；结束后打开报告目录中的 comparison.html。",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="已有审核请求 JSON，包含 brief 与完整 plan")
    source.add_argument("--topic", help="先生成这份主题的新稿，再审核；生成也会消耗模型额度")
    parser.add_argument("--output", type=Path, default=Path(".data/ppt-review"), help="报告目录，默认 .data/ppt-review")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="PPT 后端地址，默认本机 8000 端口")
    parser.add_argument("--age-group", default="4-5岁", help="年龄段，默认 4-5岁")
    parser.add_argument("--domain", default="science", help="领域，例如 science、language、math")
    parser.add_argument("--content-mode", choices=["classroom", "training"], default="classroom")
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--slides", type=int, default=8)
    parser.add_argument("--instructions", default="围绕一个核心教学目标，提供可执行的幼儿活动与教师引导。")
    parser.add_argument("--max-revisions", type=int, choices=[0, 1, 2], help="修订上限；0 表示只审核")
    parser.add_argument("--timeout", type=float, help="审核时间预算，1 到 600 秒")
    parser.add_argument("--check-only", action="store_true", help="只检查基本输入与 API 路由，不调用模型")
    parser.add_argument("--autoloop", action="store_true", help="以回执结束中台任务，已记录的审核失败不自动重试")
    return parser.parse_args()


def prepare_request(args) -> tuple[dict, dict, float]:
    parsed = urlsplit(args.api_base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise PilotError("--api-base 需要是没有账号、查询参数或片段的 PPT API 地址。")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PilotError("非本机 API 地址需要使用 HTTPS。")
    if args.input:
        if args.input.stat().st_size > 2_000_000:
            raise PilotError("审核输入超过 2 MB，请拆分材料。")
        body = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(body, dict) or not isinstance(body.get("brief"), dict) or not isinstance(body.get("plan"), dict):
            raise PilotError("输入 JSON 需要 brief 和 plan 两个对象；请勿直接传入 PPT 文件或接口外层响应。")
        brief = body["brief"]
        plan = body["plan"]
        if (not isinstance(plan.get("meta"), dict)
                or any(not isinstance(plan.get(key), list) or not plan[key]
                       for key in ("lesson_goals", "lesson_arc", "slides"))
                or any(not isinstance(slide, dict) for slide in plan["slides"])):
            raise PilotError("plan 需要包含 meta、非空 lesson_goals、lesson_arc 和 slides；每一页必须是对象。")
    else:
        brief = {"topic": args.topic, "age_group": args.age_group, "domain": args.domain,
                 "content_mode": args.content_mode, "duration_minutes": args.duration,
                 "n_slides": args.slides, "instructions": args.instructions}
        body = {"brief": brief, "max_revision_rounds": 2, "timeout_seconds": 360, "max_model_calls": 5}
    for field, default, limit in (("topic", "", 200), ("age_group", "4-5岁", 40)):
        value = brief.get(field, default)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise PilotError(f"brief.{field} 需要是 1 到 {limit} 字的文本。")
    domain = brief.get("domain", "comprehensive")
    if not isinstance(domain, str) or domain not in {"science", "language", "math", "health", "social", "art", "comprehensive"}:
        raise PilotError("brief.domain 需要使用 science、language、math、health、social、art 或 comprehensive。")
    mode = brief.get("content_mode", "classroom")
    if not isinstance(mode, str) or mode not in {"classroom", "training"}:
        raise PilotError("brief.content_mode 需要是 classroom 或 training。")
    for field, default, minimum, maximum in (("duration_minutes", 20, 5, 90), ("n_slides", None, 3, 40)):
        value = brief.get(field, default)
        if field == "n_slides" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise PilotError(f"brief.{field} 需要是 {minimum} 到 {maximum} 的整数。")
    for field, limit in (("instructions", 1000), ("source_context", 30000)):
        value = brief.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise PilotError(f"brief.{field} 需要是最多 {limit} 字的文本。")
    if args.max_revisions is not None:
        body["max_revision_rounds"] = args.max_revisions
    if args.timeout is not None:
        body["timeout_seconds"] = args.timeout
    for field, default, minimum, maximum in (("max_revision_rounds", 0, 0, 2), ("max_model_calls", 5, 1, 5)):
        value = body.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise PilotError(f"{field} 需要是 {minimum} 到 {maximum} 的整数。")
    budget = body.get("timeout_seconds", 120)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 1 <= budget <= 600:
        raise PilotError("timeout_seconds 需要是 1 到 600 的数字，不能为 null。")
    return body, brief, float(budget)


def main() -> int:
    # Autoloop captures stdout in a file. On Windows that otherwise uses the
    # local code page, which may reject Chinese or corrupt the UTF-8 receipt.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    args = _arguments()
    if args.check_only:
        try:
            prepare_request(args)
            check_api_ready(args.api_base, needs_generation=not args.input)
        except (PilotError, OSError, ValueError, TypeError) as exc:
            print(f"预检未通过：{exc}", file=sys.stderr, flush=True)
            return 2
        except KeyboardInterrupt:
            print("已停止预检，本次未提交模型请求。", file=sys.stderr, flush=True)
            return 130
        print("预检通过：基本输入有效，所需 API 路由可达。未调用模型，模型配置与模型响应尚未验证。", flush=True)
        return 0
    args.output = args.output.resolve()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = args.output / run_id
    try:
        folder.mkdir(parents=True)
    except OSError as exc:
        print(f"无法创建报告目录 {folder}：{exc}。本次未提交模型请求。", file=sys.stderr, flush=True)
        return 2
    lock = args.output / "autoloop-inflight.json"
    owns_lock, uncertain = False, False
    request_in_flight = False
    brief: dict = {}
    body: dict = {}
    report: dict = {}
    started = time.monotonic()
    try:
        body, brief, budget = prepare_request(args)
        try:
            with lock.open("x", encoding="utf-8") as handle:
                json.dump({"run_id": run_id, "report_directory": str(folder), "pid": os.getpid()}, handle)
            owns_lock = True
        except FileExistsError as exc:
            raise PilotError("同一报告目录已有正在执行或结果待核对的任务，本次没有重复提交。"
                             f"请先查看 {lock} 中记录的报告目录并核对后端任务；不会自动删除该记录。") from exc
        print(f"本次报告目录：{folder}\n[预检] 正在检查基本输入和 API 路由，不调用模型。", file=sys.stderr, flush=True)
        check_api_ready(args.api_base, needs_generation=not args.input)
        print("[预检] API 路由可达；接下来将调用后端模型。", file=sys.stderr, flush=True)
        if not args.input:
            write_json(folder / "generation-request.json", brief)
            with waiting_for("生成新稿", 660):
                request_in_flight = True
                generated = post_json(args.api_base, GENERATION_PATH, brief, 660)
                request_in_flight = False
            if not isinstance(generated.get("plan"), dict):
                raise PilotError("生成接口未返回完整教案，请查看本机 API 日志。")
            body["plan"] = generated["plan"]
            write_json(folder / "generation-response.json", generated)
        write_json(folder / "request.json", body)
        write_json(folder / "original-plan.json", body["plan"])
        with waiting_for("审核与修订", budget + 30):
            request_in_flight = True
            report = post_json(args.api_base, REVIEW_PATH, body, budget + 30)
            request_in_flight = False
        if (report.get("status") not in STATUSES or not isinstance(report.get("plan"), dict)
                or not isinstance(report.get("original_plan"), dict)
                or report.get("visual_validation") != "not_performed"):
            raise PilotError("审核接口返回的格式与当前客户端不兼容，请核对后端版本和本次任务结果。", uncertain=True)
        # Only a completed, adopted review snapshot establishes which copy was
        # actually reviewed. Failed candidate revisions are not called final.
        if report.get("review_history"):
            write_json(folder / "reviewed-plan.json", report["plan"])
    except KeyboardInterrupt:
        uncertain = request_in_flight
        original = body.get("plan", {})
        message = ("已结束本地等待；远端模型是否完成尚不明确。请先核对后端任务和本次报告，"
                   "不要重复提交；在途记录会保留。" if uncertain else "已停止本次操作；停止时没有正在等待的模型请求。")
        report = {"status": "cancelled", "message": message, "original_plan": original,
                  "plan": original, "rounds_completed": 0, "call_attempts": None, "calls": [],
                  "elapsed_ms": int((time.monotonic() - started) * 1000),
                  "visual_validation": "not_performed", "completion_unknown": uncertain,
                  "limitations": ["本次停止的是本地等待，不能据此确认远端模型已取消。", "未检查实际图片、PPT排版或导出。"]}
    except (PilotError, OSError, ValueError, TypeError) as exc:
        uncertain = exc.uncertain if isinstance(exc, PilotError) else request_in_flight
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
    print(f"PPT 审核试验结束：{label}。{report.get('message', '')}\n打开报告：{folder / 'comparison.html'}")
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
    if report.get("status") == "cancelled":
        return 130
    return 0 if report.get("status") == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
