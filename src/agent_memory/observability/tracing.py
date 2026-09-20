"""Tracing helpers.

Spans are created through :func:`span`, which runs every attribute through the
allow-list before it reaches the exporter.  Trace context is what makes a write
or read request legible end to end: HTTP handler, application service, and the
repository call underneath it appear as one tree.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, StatusCode

from agent_memory.observability.fields import sanitize

TRACER_NAME = "agent_memory"

#: The provider this package owns.  A library that overwrites the *global*
#: OpenTelemetry provider fights with whatever else the host process
#: configured -- and the global one can only be set once, which makes tests
#: awkward.  Keeping our own reference avoids both problems; spans still join
#: the ambient trace context, so a host-level tracer sees them as children.
_provider: TracerProvider | None = None


def configure_tracing(*, service_name: str, exporter: str) -> None:
    """Install a tracer provider.  ``exporter='none'`` keeps tracing inert."""
    if exporter == "none":
        set_tracer_provider(None)
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(_processor(exporter))
    set_tracer_provider(provider)


def set_tracer_provider(provider: TracerProvider | None) -> None:
    """Point this package at *provider*; ``None`` falls back to the global one."""
    global _provider
    _provider = provider


def _processor(exporter: str) -> SpanProcessor:
    exporters: dict[str, SpanExporter] = {"console": ConsoleSpanExporter()}
    if exporter not in exporters:
        raise ValueError(f"unknown trace exporter {exporter!r}")
    return SimpleSpanProcessor(exporters[exporter])


def tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer(TRACER_NAME)
    return trace.get_tracer(TRACER_NAME)


@contextmanager
def span(name: str, **attributes: object) -> Iterator[Span]:
    """Start a span whose attributes are validated against the allow-list."""
    with tracer().start_as_current_span(name, attributes=sanitize(attributes)) as current:
        try:
            yield current
        except Exception as error:
            # The type name and nothing else: exception messages quote input.
            current.set_status(StatusCode.ERROR)
            current.set_attribute("error_type", type(error).__name__)
            raise


def annotate(**attributes: object) -> None:
    """Add allow-listed attributes to the span already in progress."""
    current = trace.get_current_span()
    if not current.get_span_context().is_valid:
        return
    for key, value in sanitize(attributes).items():
        current.set_attribute(key, value)
