"""jobs — the per-request and route-level side of
registration.jobs.register_jobs, over greentechhub-core's JobRunner.

- get_job_runner(request): the JobRunner register_jobs put on the app.
- JobViews: a job's status partial (what gth_progress polls), its pause /
  resume / cancel actions and a recent-jobs page. Like NotificationViews it
  renders greentechhub-ui templates by name, passing data only: nothing
  here imports greentechhub-ui.

A service starts jobs from its own routes and answers with the status
partial, which then polls itself until the job ends:

    @app.post("/scan")
    async def start_scan(request: Request, user=Depends(require_page_identity())):
        job = await get_job_runner(request).start(
            "scan", scan_folder, label="Scan music", owner=user.subject, unique=True)
        return job_views.status_response(request, job)
"""

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.background import Job, JobRunner
from greentechhub_core.identity import Identity

from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.permissions import require_page_permission

JOBS_STATE_KEY = "gth_jobs"

STOP_POLLING = 286
"""htmx's "stop polling" status: the finished partial is still swapped in."""


@dataclass(frozen=True, slots=True, kw_only=True)
class JobsConfig:
    """What register_jobs put on app.state."""

    runner: JobRunner
    url: str | None  # JobViews' mount path, when register_jobs mounted them


def get_jobs_config(app: Any) -> JobsConfig:
    config = getattr(app.state, JOBS_STATE_KEY, None)
    if config is None:
        raise RuntimeError("no job runner: call register_jobs(app, ...) first")
    return config


def get_job_runner(request: Request) -> JobRunner:
    """The JobRunner register_jobs installed (a Depends() helper)."""
    return get_jobs_config(request.app).runner


def job_dict(job: Job) -> dict[str, Any]:
    """A Job as template data: its fields, `state` as a string, plus
    `active`, `fraction` (0..1 or None) and `percent` (0..100 or None)."""
    fraction = job.fraction
    return {
        "id": job.id,
        "kind": job.kind,
        "label": job.label,
        "owner": job.owner,
        "state": str(job.state),
        "done": job.done,
        "total": job.total,
        "message": job.message,
        "result": dict(job.result),
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "active": job.active,
        "fraction": fraction,
        "percent": round(fraction * 100) if fraction is not None else None,
    }


class JobViews:
    """A job's status partial and controls. Pass an instance to
    `register_jobs(..., views=JobViews(templates=templates))`, which mounts
    it at `url`.

    GET {url}: the recent jobs page (page_size, newest first).
    GET {url}/{id}: the job's status partial. While the job is active it
    carries `poll_url`, so the partial (a gth_job_status) polls itself; the
    answer that finds it finished is sent with status 286 to an htmx
    request, which stops the polling.
    POST {url}/{id}/pause, /resume and /cancel: do that, then answer the
    status partial.

    `permission` (optional) gates every route; without it any signed-in
    identity may use them. With `owner_only` (the default) a person sees
    and controls only their own jobs and the system's (owner None); someone
    else's job is a 404.

    Templates get, on the partial: {"job", "poll_url", "pause_url",
    "resume_url", "cancel_url", "poll_every"} with `job` a job_dict() and
    poll_url None once it's finished; on the page: {"page_title", "jobs",
    "jobs_url"} with each job a job_dict() plus "status_url". They default to
    greentechhub-ui's job templates; override the names to use your own.
    """

    status_template: str = "job_status.html"
    page_template: str = "jobs_page.html"
    url: str = "/jobs"
    login_url: str = "/login"
    title: str = "Jobs"
    icon: str = "hourglass-split"
    poll_every: str = "1s"
    page_size: int = 50
    owner_only: bool = True

    def __init__(self, *, templates: Jinja2Templates, permission: str | None = None) -> None:
        self._templates = templates
        self.permission = permission
        if permission is None:
            self._guard = require_page_identity(self.login_url)
        else:
            self._guard = require_page_permission(permission, self.login_url)

    def router(self) -> APIRouter:
        router = APIRouter()
        guard = self._guard

        async def page(request: Request, user: Identity = Depends(guard)):
            runner = get_job_runner(request)
            jobs = await runner.jobs(limit=self.page_size)
            visible = [j for j in jobs if self._may_see(user, j)]
            return self._templates.TemplateResponse(request, self.page_template, {
                "page_title": self.title,
                "jobs": [{**job_dict(j), "status_url": self._job_url(j.id)} for j in visible],
                "jobs_url": self.url,
            })

        async def status(request: Request, job_id: str, user: Identity = Depends(guard)):
            return self.status_response(request, await self._job(request, user, job_id))

        def control(action: str):
            async def act(request: Request, job_id: str, user: Identity = Depends(guard)):
                await self._job(request, user, job_id)
                runner = get_job_runner(request)
                getattr(runner, action)(job_id)
                job = await runner.get(job_id)
                assert job is not None
                return self.status_response(request, job)

            return act

        router.add_api_route(self.url, page, methods=["GET"])
        router.add_api_route(f"{self.url}/{{job_id}}", status, methods=["GET"])
        for action in ("pause", "resume", "cancel"):
            router.add_api_route(f"{self.url}/{{job_id}}/{action}", control(action),
                                 methods=["POST"])
        return router

    def status_context(self, job: Job) -> dict[str, Any]:
        """The status partial's context for `job`."""
        base = self._job_url(job.id)
        return {
            "job": job_dict(job),
            "poll_url": base if job.active else None,
            "pause_url": f"{base}/pause",
            "resume_url": f"{base}/resume",
            "cancel_url": f"{base}/cancel",
            "poll_every": self.poll_every,
        }

    def status_response(self, request: Request, job: Job):
        """The status partial for `job`: what a service's own "start" route
        answers, so the page shows the job and starts polling it."""
        status_code = 200
        if not job.active and request.headers.get("HX-Request") == "true" \
                and request.method == "GET":
            status_code = STOP_POLLING
        return self._templates.TemplateResponse(request, self.status_template,
                                                self.status_context(job),
                                                status_code=status_code)

    def _job_url(self, job_id: str) -> str:
        return f"{self.url}/{job_id}"

    def _may_see(self, user: Identity, job: Job) -> bool:
        return not self.owner_only or job.owner is None or job.owner == user.subject

    async def _job(self, request: Request, user: Identity, job_id: str) -> Job:
        job = await get_job_runner(request).get(job_id)
        if job is None or not self._may_see(user, job):
            raise HTTPException(status_code=404, detail="No such job")
        return job
