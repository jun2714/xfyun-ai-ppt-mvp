"""Actual review routes + isolated SQLite; model replies are counted fixtures.

These tests exercise the HTTP contract and session-bound ownership. They do not
use the application database, an identity provider, or a paid model endpoint.
"""
import asyncio
import copy
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request

from api.v1.ppt.endpoints import kindergarten_review as endpoint
from services.database import get_async_session
from test_kindergarten_presentation_review_service import (
    Caller, _database, _request, _revision_steps,
)


@asynccontextmanager
async def _client(db, monkeypatch, caller):
    app = FastAPI()

    async def session_dependency(request: Request):
        owner = db.other_owner if request.headers.get("x-test-owner") == "other" else db.owner
        async with db.session(owner) as session:
            yield session

    app.dependency_overrides[get_async_session] = session_dependency
    app.include_router(endpoint.KINDERGARTEN_REVIEW_ROUTER, prefix="/api/v1/ppt")
    monkeypatch.setattr(endpoint, "OpenAICompatibleReviewCaller", lambda: caller)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://review.test") as client:
        yield client, f"/api/v1/ppt/kindergarten/presentation/{db.id}"


def test_review_http_roundtrip_reuses_request_id_without_another_model_call(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            caller = Caller()
            async with _client(db, monkeypatch, caller) as (client, base):
                source = await client.get(base + "/review-source")
                assert source.status_code == 200, source.text
                assert source.json()["available"] is True
                assert source.json()["source_version"] == db.source["source_version"]
                payload = _request(db).model_dump(mode="json")
                first = await client.post(base + "/review", json=payload)
                repeated = await client.post(base + "/review", json=payload)
                assert first.status_code == repeated.status_code == 200
                assert first.json()["result"]["status"] == "passed"
                assert repeated.json()["review_id"] == first.json()["review_id"]
                assert len(caller.calls) == 1
                saved = await client.get(base + "/review-source")
                assert saved.status_code == 200
                assert saved.json()["latest_review"]["review_id"] == first.json()["review_id"]
                assert saved.json()["active_review"] is None
                assert (await db.row()).outlines == db.source["outline"]
    asyncio.run(run())


def test_all_review_routes_reject_another_owner_before_model_or_apply(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            caller = Caller()
            async with _client(db, monkeypatch, caller) as (client, base):
                headers = {"x-test-owner": "other"}
                responses = [
                    await client.get(base + "/review-source", headers=headers),
                    await client.post(base + "/review", headers=headers, json=_request(db).model_dump(mode="json")),
                    await client.post(base + "/review/apply", headers=headers, json={
                        "review_id": str(uuid4()), "source_version": db.source["source_version"],
                    }),
                ]
                assert [response.status_code for response in responses] == [404, 404, 404]
                assert all(response.json()["detail"]["code"] == "presentation_not_found" for response in responses)
                assert not caller.calls
                assert (await db.row()).outlines == db.source["outline"]
    asyncio.run(run())


def test_old_http_report_cannot_overwrite_a_manually_saved_outline(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            caller = Caller(*_revision_steps())
            async with _client(db, monkeypatch, caller) as (client, base):
                reviewed = await client.post(base + "/review", json=_request(db, max_revision_rounds=1).model_dump(mode="json"))
                assert reviewed.status_code == 200, reviewed.text
                result = reviewed.json()
                assert result["can_apply"] is True
                edited = copy.deepcopy(db.source["outline"])
                edited["slides"][1]["content"] = "教师在另一页签保存的新内容"
                await db.mutate(outlines=edited)
                source = await client.get(base + "/review-source")
                assert source.status_code == 200
                assert source.json()["reason"] == "outline_changed"
                assert source.json()["latest_review"]["stale"] is True
                assert source.json()["apply_available"] is False
                refused = await client.post(base + "/review/apply", json={
                    "review_id": result["review_id"], "source_version": result["source_version"],
                })
                assert refused.status_code == 409
                assert refused.json()["detail"]["code"] == "outline_changed"
                assert (await db.row()).outlines == edited
                assert len(caller.calls) == 3
    asyncio.run(run())


def test_reviewed_changes_write_outline_only_after_explicit_http_apply(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            caller = Caller(*_revision_steps())
            before = copy.deepcopy((await db.row()).outlines)
            async with _client(db, monkeypatch, caller) as (client, base):
                request = _request(db, max_revision_rounds=1).model_dump(mode="json")
                reviewed = await client.post(base + "/review", json=request)
                assert reviewed.status_code == 200, reviewed.text
                result = reviewed.json()
                assert result["can_apply"] is True and result["changed_slide_numbers"] == [2]
                assert (await db.row()).outlines == before
                source = await client.get(base + "/review-source")
                assert source.status_code == 200 and source.json()["apply_available"] is True
                repeated_review = await client.post(base + "/review", json=request)
                assert repeated_review.status_code == 200
                assert repeated_review.json()["review_id"] == result["review_id"]
                assert (await db.row()).outlines == before
                assert len(caller.calls) == 3

                apply_payload = {"review_id": result["review_id"], "source_version": result["source_version"]}
                adopted = await client.post(base + "/review/apply", json=apply_payload)
                assert adopted.status_code == 200, adopted.text
                after = (await db.row()).outlines
                assert after["slides"][1]["content_contract"]["screen_title"] == "观察海龟与海豚"
                assert after["slides"][0] == before["slides"][0]
                assert after["slides"][2] == before["slides"][2]
                assert adopted.json()["source_version"] != result["source_version"]

                saved = await client.get(base + "/review-source")
                assert saved.json()["latest_review"]["applied"] is True
                assert saved.json()["apply_available"] is False
                repeated_apply = await client.post(base + "/review/apply", json=apply_payload)
                assert repeated_apply.status_code == 200
                assert repeated_apply.json()["source_version"] == adopted.json()["source_version"]
                assert (await db.row()).outlines == after
                assert len(caller.calls) == 3
    asyncio.run(run())
