"""Cross-cutting observability: structured logs, traces and metrics.

This package is a leaf: it imports nothing from ``domain``, ``application``,
``infrastructure`` or ``api``, so the layers above may use it without creating
a cycle or pointing a dependency outward.
"""

from agent_memory.observability.context import (
    bind_tenant,
    correlation,
    current_request_id,
    current_tenant_id,
)
from agent_memory.observability.fields import UnsafeTelemetryField
from agent_memory.observability.logging import configure_logging, get_logger
from agent_memory.observability.metrics import (
    configure_metrics,
    record_job,
    record_operation,
    record_request,
    reset_instruments,
    set_meter_provider,
)
from agent_memory.observability.tracing import (
    annotate,
    configure_tracing,
    set_tracer_provider,
    span,
)

__all__ = [
    "UnsafeTelemetryField",
    "annotate",
    "bind_tenant",
    "configure_logging",
    "configure_metrics",
    "configure_tracing",
    "correlation",
    "current_request_id",
    "current_tenant_id",
    "get_logger",
    "record_job",
    "record_operation",
    "record_request",
    "reset_instruments",
    "set_meter_provider",
    "set_tracer_provider",
    "span",
]
