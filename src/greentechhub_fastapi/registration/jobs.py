"""register_jobs — puts a greentechhub-core JobRunner on the app for
background jobs (scans, imports, builds) with progress, pause/cancel and a
result, and optionally mounts JobViews.

Opt-in like every register_* call. It:
  - builds the JobRunner (over `store`, InMemoryJobStore by default) and
    stores it on app.state, where get_job_runner finds it;
  - wraps the app's lifespan so shutdown cancels the jobs still running;
  - subscribes to core's JobFinished: with `audit` (the default) each
    finished job is recorded as jobs.succeeded / jobs.failed /
    jobs.cancelled (a no-op until register_audit ran), and with `notify`
    its owner gets a notification (register_notifications needed);
  - mounts `views` (a JobViews) when given.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from greentechhub_core.background import (
    InMemoryJobStore,
    JobFinished,
    JobRunner,
    JobState,
    JobStore,
    Lock,
)
from greentechhub_core.events import EventBus, default_event_bus

from greentechhub_fastapi.audit import record_audit
from greentechhub_fastapi.jobs import JOBS_STATE_KEY, JobsConfig, JobViews

logger = logging.getLogger(__name__)

_TOAST_KIND = {JobState.SUCCEEDED: "success", JobState.FAILED: "danger",
               JobState.CANCELLED: "warning"}
_VERB = {JobState.SUCCEEDED: "finished", JobState.FAILED: "failed",
         JobState.CANCELLED: "was cancelled"}


def register_jobs(
    app: FastAPI,
    settings: Any,
    *,
    store: JobStore | None = None,
    views: JobViews | None = None,
    audit: bool = True,
    notify: bool = False,
    event_bus: EventBus | None = None,
    lock: Lock | None = None,
) -> JobRunner:
    """Install the app's JobRunner and return it. `settings` is the
    service's GTHBaseSettings, accepted for symmetry with the other
    register_* calls. `lock` makes `start(..., unique=True)` hold across
    processes (e.g. a FileLock in settings.lock_directory())."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_jobs must run before the app starts")
    bus = event_bus if event_bus is not None else default_event_bus
    runner = JobRunner(store if store is not None else InMemoryJobStore(), event_bus=bus,
                       lock=lock)
    setattr(app.state, JOBS_STATE_KEY,
            JobsConfig(runner=runner, url=views.url if views is not None else None))

    async def on_finished(event: JobFinished) -> None:
        job = event.job
        if await runner.store.get(job.id) is None:  # another app's runner
            return
        if audit:
            details = {"kind": job.kind, "done": job.done, "total": job.total}
            if job.error:
                details["error"] = job.error
            await record_audit(app, f"jobs.{job.state}", actor=job.owner,
                               target=("job", job.id), summary=f"{job.label} {_VERB[job.state]}",
                               details=details)
        if notify and job.owner is not None:
            await _notify_owner(app, job)

    # Subscribed now, not at startup, so it also works where the lifespan
    # never runs (a test client without it); shutdown unsubscribes.
    bus.subscribe(JobFinished, on_finished)
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        try:
            async with previous_lifespan(app) as state:
                yield state
        finally:
            await runner.shutdown()
            bus.unsubscribe(JobFinished, on_finished)

    app.router.lifespan_context = _lifespan

    if views is not None:
        app.include_router(views.router())
    return runner


async def _notify_owner(app: FastAPI, job: Any) -> None:
    # Imported here: notifications imports auth, whose views import audit.
    from greentechhub_fastapi.notifications import NOTIFICATIONS_STATE_KEY
    from greentechhub_fastapi.notifications import notify as notify_person

    if getattr(app.state, NOTIFICATIONS_STATE_KEY, None) is None:
        logger.warning("register_jobs(notify=True) needs register_notifications; "
                       "job %s not notified", job.id)
        return
    message = f"{job.label} {_VERB[job.state]}"
    if job.error:
        message += f": {job.error}"
    await notify_person(app, job.owner, {"message": message, "kind": _TOAST_KIND[job.state]},
                        category="jobs")
