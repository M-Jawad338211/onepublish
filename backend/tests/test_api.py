"""REST API tests through httpx's ASGI transport against the test database."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import respx
from sqlmodel import select

from app import crypto
from app.db import utcnow
from app.models import DownloadStatus, Job, JobState, OAuthState, Target, Token, Video
from app.services import youtube
from app.services.tiktok import API_BASE

pytestmark = pytest.mark.db

CHANNEL = "UC" + "b" * 22


@pytest.fixture
def fake_resolve(monkeypatch):
    async def resolve(url, client=None):
        return youtube.ChannelInfo(CHANNEL, "My Channel", "@mine", url, None)

    monkeypatch.setattr(youtube, "resolve_channel", resolve)


async def test_auth_required_and_login(client):
    assert (await client.get("/api/sources")).status_code == 401
    assert (await client.get("/api/auth/me")).json() == {"authenticated": False}
    bad = await client.post("/api/auth/login", json={"password": "nope"})
    assert bad.status_code == 401
    ok = await client.post("/api/auth/login", json={"password": "hunter2"})
    assert ok.status_code == 200 and "op_session" in ok.cookies
    assert (await client.get("/api/auth/me")).json() == {"authenticated": True}
    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await client.get("/api/sources")).status_code == 401


async def test_health_is_public(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "db": True}


async def test_source_lifecycle(authed, fake_resolve):
    r = await authed.post("/api/sources", json={"url": "https://www.youtube.com/@mine"})
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["shorts_playlist_id"] == "UUSH" + "b" * 22
    assert src["poll_interval_s"] == 600 and src["status"] == "ACTIVE"

    dup = await authed.post("/api/sources", json={"url": "https://www.youtube.com/@mine"})
    assert dup.status_code == 409

    too_fast = await authed.patch(f"/api/sources/{src['id']}", json={"poll_interval_s": 30})
    assert too_fast.status_code == 422
    paused = await authed.patch(f"/api/sources/{src['id']}", json={"status": "PAUSED"})
    assert paused.json()["status"] == "PAUSED"
    assert (await authed.post(f"/api/sources/{src['id']}/check-now")).status_code == 200
    assert (await authed.delete(f"/api/sources/{src['id']}")).status_code == 204
    assert (await authed.get("/api/sources")).json() == []


async def _target(db, name="tt_one") -> Target:
    t = Target(open_id=f"open-{name}", display_name=name)
    db.add(t)
    await db.flush()
    db.add(
        Token(
            target_id=t.id,
            access_token_enc=crypto.encrypt("a"),
            access_expires_at=utcnow() + timedelta(hours=1),
            refresh_token_enc=crypto.encrypt("r"),
            refresh_expires_at=utcnow() + timedelta(days=200),
        )
    )
    await db.commit()
    return t


async def test_mappings_and_caption_preview(authed, db, fake_resolve):
    src = (await authed.post("/api/sources", json={"url": "youtube.com/@mine"})).json()
    target = await _target(db)
    body = {"source_id": src["id"], "target_id": target.id, "extra_tags": ["#brand", " "]}
    r = await authed.post("/api/mappings", json=body)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["extra_tags"] == ["brand"] and m["strip_tags"] == ["shorts"]
    assert (await authed.post("/api/mappings", json=body)).status_code == 409

    upd = await authed.patch(f"/api/mappings/{m['id']}", json={"enabled": False, "max_len": 100})
    assert upd.json()["enabled"] is False and upd.json()["max_len"] == 100

    preview = await authed.post(
        "/api/mappings/caption-preview",
        json={"title": "T", "description": "see https://x.y #shorts", "tags": ["a b"]},
    )
    assert preview.json()["caption"] == "T\n\nsee\n\n#ab"


async def test_targets_show_quota(authed, db):
    target = await _target(db)
    for i in range(2):
        v = Video(yt_video_id=f"q{i:010d}", download_status=DownloadStatus.DELETED)
        db.add(v)
        await db.flush()
        db.add(
            Job(
                video_id=v.id,
                target_id=target.id,
                state=JobState.SEND_TO_USER_INBOX,
                uploaded_at=utcnow() - timedelta(hours=1),
            )
        )
    await db.commit()
    [t] = (await authed.get("/api/targets")).json()
    assert t["quota_used"] == 2 and t["quota_cap"] == 5 and t["next_slot_at"] is None
    assert t["refresh_expires_at"] is not None
    assert "access_token_enc" not in t


async def test_job_list_retry_skip_resend(authed, db):
    t1 = await _target(db, "one")
    t2 = await _target(db, "two")
    v = Video(yt_video_id="vid00000009", title="Clip", download_status=DownloadStatus.DELETED)
    db.add(v)
    await db.flush()
    failed = Job(
        video_id=v.id,
        target_id=t1.id,
        state=JobState.FAILED,
        last_error="boom",
        attempts=5,
        publish_id="p",
    )
    db.add(failed)
    await db.commit()

    page = (await authed.get("/api/jobs", params={"state": ["FAILED"]})).json()
    assert [j["id"] for j in page["items"]] == [failed.id] and page["next_cursor"] is None
    assert page["items"][0]["video"]["url"].endswith("/shorts/vid00000009")

    retried = (await authed.post(f"/api/jobs/{failed.id}/retry")).json()
    assert retried["state"] == "QUEUED" and retried["attempts"] == 0
    assert retried["publish_id"] is None
    await db.refresh(v)
    assert v.download_status == DownloadStatus.NEW  # file was gone, so it re-downloads

    resent = await authed.post(f"/api/jobs/{failed.id}/resend", json={"target_id": t2.id})
    assert resent.status_code == 201 and resent.json()["target_name"] == "two"
    again = await authed.post(f"/api/jobs/{failed.id}/resend", json={"target_id": t2.id})
    assert again.status_code == 409

    skipped = await authed.post(f"/api/jobs/{failed.id}/skip")
    assert skipped.json()["state"] == "SKIPPED"
    detail = (await authed.get(f"/api/jobs/{failed.id}")).json()
    assert [e["message"] for e in detail["events"]][:1] == ["Retry requested"]


async def test_alerts_read_flow(authed, db):
    from app.models import AlertKind
    from app.services.alerts import raise_alert

    await raise_alert(db, AlertKind.DISK_HIGH, "disk", dedupe_key="disk-high")
    await raise_alert(db, AlertKind.DISK_HIGH, "disk again", dedupe_key="disk-high")
    await db.commit()
    assert (await authed.get("/api/alerts/unread-count")).json() == {"unread": 1}
    await authed.post("/api/alerts/read-all")
    assert (await authed.get("/api/alerts/unread-count")).json() == {"unread": 0}
    # Once read, the same condition can alert again.
    await raise_alert(db, AlertKind.DISK_HIGH, "disk later", dedupe_key="disk-high")
    await db.commit()
    assert len((await authed.get("/api/alerts")).json()) == 2


@respx.mock
async def test_tiktok_connect_and_callback(authed, db):
    r = await authed.get("/api/tiktok/connect", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == ["user.info.basic,video.upload"]
    assert q["code_challenge_method"] == ["S256"]
    state = q["state"][0]
    saved = await db.get(OAuthState, state)
    assert saved is not None

    respx.post(f"{API_BASE}/v2/oauth/token/").respond(
        json={
            "open_id": "open-new",
            "access_token": "acc",
            "expires_in": 86400,
            "refresh_token": "ref",
            "refresh_expires_in": 31536000,
            "scope": "user.info.basic,video.upload",
            "token_type": "Bearer",
        }
    )
    respx.get(f"{API_BASE}/v2/user/info/").respond(
        json={
            "data": {
                "user": {
                    "open_id": "open-new",
                    "display_name": "New One",
                    "avatar_url": "https://a",
                }
            },
            "error": {"code": "ok", "message": "", "log_id": "x"},
        }
    )
    cb = await authed.get(
        "/api/tiktok/callback", params={"code": "c", "state": state}, follow_redirects=False
    )
    assert cb.status_code == 302 and "connected=New+One" in cb.headers["location"]

    target = (await db.exec(select(Target).where(Target.open_id == "open-new"))).one()
    token = await db.get(Token, target.id)
    assert crypto.decrypt(token.refresh_token_enc) == "ref"
    assert token.access_token_enc != "acc"

    replay = await authed.get(
        "/api/tiktok/callback", params={"code": "c", "state": state}, follow_redirects=False
    )
    assert "error=" in replay.headers["location"]


async def test_retry_now_clears_backoff(authed, db):
    t = await _target(db)
    v = Video(
        yt_video_id="wait0000009",
        download_status=DownloadStatus.NEW,
        next_attempt_at=utcnow() + timedelta(hours=1),
    )
    db.add(v)
    await db.flush()
    job = Job(video_id=v.id, target_id=t.id, next_attempt_at=utcnow() + timedelta(hours=1))
    db.add(job)
    await db.commit()
    r = await authed.post(f"/api/jobs/{job.id}/retry")
    assert r.status_code == 200 and r.json()["next_attempt_at"] is None
    await db.refresh(v)
    assert v.next_attempt_at is None
