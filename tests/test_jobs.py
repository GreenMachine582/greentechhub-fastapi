"""register_jobs and JobViews: a JobRunner on the app, a status partial that
polls itself until the job ends (286 then), pause/resume/cancel, owner-only
visibility, and an audit entry or notification when a job finishes."""

import asyncio
import threading

import httpx
import pytest
from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.audit import InMemoryAuditStore
from greentechhub_core.background import JobContext, JobState
from greentechhub_core.events import EventBus
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from greentechhub_core.notifications import InMemoryNotificationStore

from greentechhub_fastapi import register_audit, register_jobs, register_notifications
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.jobs import STOP_POLLING, JobViews, get_job_runner, job_dict
from tests.conftest import build_app

# Stand-ins for greentechhub-ui's job templates: they print the data.
STATUS = ("JOB {{ job.label }} {{ job.state }} {{ job.done }}/{{ job.total }} "
          "pct={{ job.percent }} poll={{ poll_url or '-' }} cancel={{ cancel_url }} "
          "every={{ poll_every }} files={{ job.result.files }} error={{ job.error }}")
PAGE = ("{{ page_title }}\n{% for j in jobs %}ROW {{ j.label }} {{ j.state }} "
        "{{ j.status_url }}\n{% endfor %}")


@pytest.fixture
def templates(tmp_path):
    (tmp_path / "job_status.html").write_text(STATUS, encoding="utf-8")
    (tmp_path / "jobs_page.html").write_text(PAGE, encoding="utf-8")
    return Jinja2Templates(directory=tmp_path)


def _cookie(subject):
    provider = DevelopmentIdentityProvider(secret_key="test-secret")
    return {"gth_session": provider.issue(
        Identity(subject=subject, username=subject, email=None, groups=[], claims={}))}


def _client(app, subject="alice"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             cookies=_cookie(subject) if subject else None)


def _app(settings, templates, **kwargs):
    app = build_app(settings)
    views = JobViews(templates=templates)
    runner = register_jobs(app, settings, views=views, event_bus=EventBus(), **kwargs)
    return app, runner, views


def test_start_poll_and_finish(settings, templates):
    app, runner, views = _app(settings, templates)
    gate = threading.Event()

    def scan(ctx: JobContext):
        ctx.progress(1, 4, message="a.mp3")
        gate.wait(5)
        ctx.checkpoint_sync()
        ctx.progress(4, 4)
        return {"files": 4}

    @app.post("/scan")
    async def start(request: Request, user: Identity = Depends(require_page_identity())):
        job = await get_job_runner(request).start("scan", scan, label="Scan music",
                                                  owner=user.subject)
        return views.status_response(request, job)

    async def main():
        async with _client(app) as client:
            started = await client.post("/scan")
            job_id = next(iter(runner._live))
            while (await runner.get(job_id)).done != 1:
                await asyncio.sleep(0.01)
            running = await client.get(f"/jobs/{job_id}", headers={"HX-Request": "true"})
            gate.set()
            await runner.wait(job_id)
            done = await client.get(f"/jobs/{job_id}", headers={"HX-Request": "true"})
            plain = await client.get(f"/jobs/{job_id}")
            page = await client.get("/jobs")
        return job_id, started, running, done, plain, page

    job_id, started, running, done, plain, page = asyncio.run(main())
    assert started.status_code == 200 and started.text.startswith("JOB Scan music queued")
    assert f"poll=/jobs/{job_id} " in started.text
    assert running.status_code == 200
    assert f"JOB Scan music running 1/4 pct=25 poll=/jobs/{job_id} " in running.text
    assert f"cancel=/jobs/{job_id}/cancel every=1s" in running.text
    assert done.status_code == STOP_POLLING
    assert "succeeded 4/4 pct=100 poll=- " in done.text and "files=4 " in done.text
    assert plain.status_code == 200
    assert page.text.splitlines() == ["Jobs", f"ROW Scan music succeeded /jobs/{job_id}"]


def test_pause_resume_and_cancel(settings, templates):
    app, runner, _ = _app(settings, templates)

    async def forever(ctx: JobContext):
        while True:
            await ctx.checkpoint()
            await asyncio.sleep(0.01)

    async def main():
        job = await runner.start("scan", forever, owner="alice")
        async with _client(app) as client:
            paused = await client.post(f"/jobs/{job.id}/pause")
            resumed = await client.post(f"/jobs/{job.id}/resume")
            cancelled = await client.post(f"/jobs/{job.id}/cancel")
            await runner.wait(job.id, timeout=5)
            after = await client.get(f"/jobs/{job.id}")
        return paused, resumed, cancelled, after

    paused, resumed, cancelled, after = asyncio.run(main())
    assert " paused " in paused.text and " running " in resumed.text
    assert cancelled.status_code == 200
    assert " cancelled " in after.text and "poll=- " in after.text


def test_owner_only_hides_other_peoples_jobs(settings, templates):
    app, runner, _ = _app(settings, templates)

    async def quick(ctx: JobContext):
        return None

    async def main():
        mine = await runner.start("scan", quick, label="mine", owner="alice")
        theirs = await runner.start("scan", quick, label="theirs", owner="bob")
        system = await runner.start("scan", quick, label="system")
        for job in (mine, theirs, system):
            await runner.wait(job.id)
        async with _client(app, "alice") as client:
            page = await client.get("/jobs")
            other = await client.get(f"/jobs/{theirs.id}")
            cancel = await client.post(f"/jobs/{theirs.id}/cancel")
            missing = await client.get("/jobs/nope")
        async with _client(app, None) as anonymous:
            anon = await anonymous.get(f"/jobs/{mine.id}", headers={"Accept": "text/html"})
        return page, other, cancel, missing, anon

    page, other, cancel, missing, anon = asyncio.run(main())
    labels = [line.split()[1] for line in page.text.splitlines() if line.startswith("ROW")]
    assert sorted(labels) == ["mine", "system"]
    assert other.status_code == cancel.status_code == missing.status_code == 404
    assert anon.status_code == 303


def test_finished_jobs_are_audited(settings, templates):
    app, runner, _ = _app(settings, templates)
    store = InMemoryAuditStore()
    register_audit(app, settings, store=store)

    def fails(ctx: JobContext):
        raise OSError("drive not ready")

    async def main():
        job = await runner.start("scan", fails, label="Scan music", owner="alice")
        await runner.wait(job.id)
        return job

    job = asyncio.run(main())
    [entry] = store.entries_sync()
    assert (entry.action, entry.actor, entry.target_type, entry.target_id) == (
        "jobs.failed", "alice", "job", job.id)
    assert entry.summary == "Scan music failed"
    assert entry.details["error"] == "drive not ready" and entry.details["kind"] == "scan"


def test_audit_can_be_turned_off(settings, templates):
    app, runner, _ = _app(settings, templates, audit=False)
    store = InMemoryAuditStore()
    register_audit(app, settings, store=store)

    async def main():
        job = await runner.start("scan", lambda ctx: None)
        await runner.wait(job.id)

    asyncio.run(main())
    assert store.entries_sync() == []


def test_notify_tells_the_owner(settings, templates):
    app, runner, _ = _app(settings, templates, notify=True)
    notes = InMemoryNotificationStore()
    register_notifications(app, settings, store=notes)

    async def main():
        a = await runner.start("scan", lambda ctx: {"files": 3}, label="Scan music",
                               owner="alice")
        b = await runner.start("scan", lambda ctx: None, label="Nightly")  # no owner
        await runner.wait(a.id)
        await runner.wait(b.id)

    asyncio.run(main())
    [note] = notes.list_for_sync("alice")
    assert (note.message, note.kind, note.category) == ("Scan music finished", "success", "jobs")


def test_notify_without_notifications_only_warns(settings, templates, caplog):
    app, runner, _ = _app(settings, templates, notify=True)

    async def main():
        job = await runner.start("scan", lambda ctx: None, owner="alice")
        await runner.wait(job.id)

    asyncio.run(main())
    assert "needs register_notifications" in caplog.text


def test_another_apps_jobs_are_ignored(settings, templates):
    bus = EventBus()
    app_a = build_app(settings)
    app_b = build_app(settings)
    runner_a = register_jobs(app_a, settings, event_bus=bus)
    register_jobs(app_b, settings, event_bus=bus)
    store_b = InMemoryAuditStore()
    register_audit(app_b, settings, store=store_b)

    async def main():
        job = await runner_a.start("scan", lambda ctx: None)
        await runner_a.wait(job.id)

    asyncio.run(main())
    assert store_b.entries_sync() == []


def test_shutdown_cancels_running_jobs(settings, templates):
    app, runner, _ = _app(settings, templates)

    async def forever(ctx: JobContext):
        while True:
            await ctx.checkpoint()
            await asyncio.sleep(0.01)

    async def main():
        async with app.router.lifespan_context(app):
            job = await runner.start("scan", forever)
            await asyncio.sleep(0.02)
        return await runner.get(job.id)

    assert asyncio.run(main()).state is JobState.CANCELLED


def test_job_dict_percent():
    from greentechhub_core.background import new_job

    job = new_job("scan")
    assert job_dict(job)["percent"] is None and job_dict(job)["state"] == "queued"


def test_register_jobs_before_start_only(settings):
    app = build_app(settings)
    app.middleware_stack = app.build_middleware_stack()
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_jobs(app, settings)
