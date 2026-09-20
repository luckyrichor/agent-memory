"""Single entry point that turns the settings into a configured pipeline."""

from __future__ import annotations

from agent_memory.config import Settings
from agent_memory.observability.logging import configure_logging
from agent_memory.observability.metrics import configure_metrics, reset_instruments
from agent_memory.observability.tracing import configure_tracing


def configure_observability(settings: Settings) -> None:
    """Configure logs, traces and metrics from ``MEMORY_*`` settings.

    Exporters default to ``none``: an unconfigured deployment stays silent
    rather than writing spans to stdout.
    """
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json_output=settings.log_json,
    )
    configure_tracing(service_name=settings.service_name, exporter=settings.trace_exporter)
    configure_metrics(service_name=settings.service_name, exporter=settings.metrics_exporter)
    reset_instruments()
