"""Metrics.

Four instruments cover the M1 acceptance bar: request rate and latency at the
edge, and the write/read outcomes of the memory service plus the worker's job
results.  Labels come from the same allow-list as spans and logs, which keeps
cardinality bounded and content out.
"""

from __future__ import annotations

from typing import Final

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from agent_memory.observability.fields import sanitize

METER_NAME: Final = "agent_memory"

#: Owned for the same reason as the tracer provider -- see ``tracing.py``.
_provider: MeterProvider | None = None


def configure_metrics(*, service_name: str, exporter: str, interval_ms: int = 60_000) -> None:
    """Install a meter provider.  ``exporter='none'`` keeps metrics inert."""
    if exporter == "none":
        set_meter_provider(None)
        return
    set_meter_provider(
        MeterProvider(
            resource=Resource.create({SERVICE_NAME: service_name}),
            metric_readers=[_reader(exporter, interval_ms)],
        )
    )


def set_meter_provider(provider: MeterProvider | None) -> None:
    """Point this package at *provider*; ``None`` falls back to the global one."""
    global _provider
    _provider = provider
    reset_instruments()


def _reader(exporter: str, interval_ms: int) -> MetricReader:
    if exporter != "console":
        raise ValueError(f"unknown metrics exporter {exporter!r}")
    return PeriodicExportingMetricReader(
        ConsoleMetricExporter(),
        export_interval_millis=interval_ms,
    )


class _Instruments:
    """Lazily created instruments, so the meter provider can be swapped in tests."""

    def __init__(self) -> None:
        self._meter: metrics.Meter | None = None
        self._requests: metrics.Counter | None = None
        self._latency: metrics.Histogram | None = None
        self._operations: metrics.Counter | None = None
        self._jobs: metrics.Counter | None = None

    def reset(self) -> None:
        self._meter = None
        self._requests = None
        self._latency = None
        self._operations = None
        self._jobs = None

    def _get_meter(self) -> metrics.Meter:
        if self._meter is None:
            self._meter = (
                _provider.get_meter(METER_NAME)
                if _provider is not None
                else metrics.get_meter(METER_NAME)
            )
        return self._meter

    @property
    def requests(self) -> metrics.Counter:
        if self._requests is None:
            self._requests = self._get_meter().create_counter(
                "agent_memory.http.requests",
                unit="1",
                description="HTTP requests handled, labelled by route and status",
            )
        return self._requests

    @property
    def latency(self) -> metrics.Histogram:
        if self._latency is None:
            self._latency = self._get_meter().create_histogram(
                "agent_memory.http.duration",
                unit="ms",
                description="Wall-clock duration of HTTP requests",
            )
        return self._latency

    @property
    def operations(self) -> metrics.Counter:
        if self._operations is None:
            self._operations = self._get_meter().create_counter(
                "agent_memory.memory.operations",
                unit="1",
                description="Memory service outcomes, labelled by action and reason code",
            )
        return self._operations

    @property
    def jobs(self) -> metrics.Counter:
        if self._jobs is None:
            self._jobs = self._get_meter().create_counter(
                "agent_memory.worker.jobs",
                unit="1",
                description="Extraction jobs processed, labelled by outcome",
            )
        return self._jobs


_instruments = _Instruments()


def reset_instruments() -> None:
    """Drop cached instruments.  Tests call this after installing a provider."""
    _instruments.reset()


def record_request(*, route: str, http_method: str, http_status: int, duration_ms: float) -> None:
    labels = sanitize({"route": route, "http_method": http_method, "http_status": http_status})
    _instruments.requests.add(1, labels)
    _instruments.latency.record(duration_ms, labels)


def record_operation(*, action: str, decision: str, reason_code: str) -> None:
    _instruments.operations.add(
        1,
        sanitize({"action": action, "decision": decision, "reason_code": reason_code}),
    )


def record_job(*, outcome: str, reason_code: str) -> None:
    _instruments.jobs.add(1, sanitize({"outcome": outcome, "reason_code": reason_code}))
