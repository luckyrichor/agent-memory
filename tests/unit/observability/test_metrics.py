from collections.abc import Iterator

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from agent_memory.observability import (
    record_job,
    record_operation,
    record_request,
    set_meter_provider,
)


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    set_meter_provider(MeterProvider(metric_readers=[reader]))
    try:
        yield reader
    finally:
        set_meter_provider(None)


def points(reader: InMemoryMetricReader, name: str) -> list[object]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_request_counter_and_latency_share_the_same_labels(
    reader: InMemoryMetricReader,
) -> None:
    record_request(
        route="/v1/memories/{memory_id}",
        http_method="GET",
        http_status=200,
        duration_ms=12.5,
    )

    counted = points(reader, "agent_memory.http.requests")
    measured = points(reader, "agent_memory.http.duration")
    assert [point.value for point in counted] == [1]  # type: ignore[attr-defined]
    assert [point.sum for point in measured] == [12.5]  # type: ignore[attr-defined]
    assert counted[0].attributes == measured[0].attributes  # type: ignore[attr-defined]


def test_metric_labels_use_the_route_template_not_the_concrete_path(
    reader: InMemoryMetricReader,
) -> None:
    """Concrete paths carry memory ids, which would explode label cardinality."""
    record_request(
        route="/v1/memories/{memory_id}",
        http_method="GET",
        http_status=200,
        duration_ms=1.0,
    )

    attributes = points(reader, "agent_memory.http.requests")[0].attributes  # type: ignore[attr-defined]
    assert attributes["route"] == "/v1/memories/{memory_id}"


def test_operation_and_job_outcomes_are_counted_by_reason_code(
    reader: InMemoryMetricReader,
) -> None:
    record_operation(action="memory.remember", decision="allow", reason_code="MEMORY_CREATED")
    record_operation(action="memory.remember", decision="deny", reason_code="MEMORY_SCOPE_FORBIDDEN")
    record_job(outcome="succeeded", reason_code="JOB_SUCCEEDED")

    operations = points(reader, "agent_memory.memory.operations")
    jobs = points(reader, "agent_memory.worker.jobs")
    decisions = {point.attributes["decision"] for point in operations}  # type: ignore[attr-defined]
    assert decisions == {"allow", "deny"}
    assert [point.attributes["outcome"] for point in jobs] == ["succeeded"]  # type: ignore[attr-defined]
