from greentechhub_core.health import HealthResult

from greentechhub_fastapi.health.render import overall_status, render_health_results


def _healthy(detail="fine"):
    return HealthResult(status="healthy", detail=detail, latency_ms=1.0)


def _unhealthy(detail="broken"):
    return HealthResult(status="unhealthy", detail=detail, latency_ms=1.0)


def test_overall_status_healthy_when_all_checks_healthy():
    assert overall_status([_healthy(), _healthy()]) == "healthy"


def test_overall_status_unhealthy_when_any_check_unhealthy():
    assert overall_status([_healthy(), _unhealthy()]) == "unhealthy"


def test_overall_status_healthy_for_empty_list():
    assert overall_status([]) == "healthy"


def test_render_health_results_shape():
    body = render_health_results([_healthy(detail="db ok"), _unhealthy(detail="cache down")])

    assert body["status"] == "unhealthy"
    assert len(body["checks"]) == 2
    for check in body["checks"]:
        assert set(check) == {"status", "detail", "latency_ms"}
    assert body["checks"][0]["detail"] == "db ok"
    assert body["checks"][1]["detail"] == "cache down"
