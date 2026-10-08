import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from agent_memory.observability import set_tracer_provider, span


def test_real_otlp_http_export_and_exception_text_redaction() -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    traces = TracerProvider()
    traces.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint + "/v1/traces"))
    )
    metrics = MeterProvider(
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint + "/v1/metrics"), export_interval_millis=60000
            )
        ]
    )
    set_tracer_provider(traces)
    try:
        with pytest.raises(ValueError), span("safe-operation"):
            raise ValueError("do-not-export-this-private-text")
        metrics.get_meter("test").create_counter("test.counter").add(1)
        metrics.force_flush()
        assert {path for path, _ in received} == {"/v1/traces", "/v1/metrics"}
        assert any(b"safe-operation" in wire for _, wire in received)
        assert not any(b"do-not-export-this-private-text" in wire for _, wire in received)
    finally:
        set_tracer_provider(None)
        traces.shutdown()
        metrics.shutdown()
        server.shutdown()
        server.server_close()
        thread.join()
