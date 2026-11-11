"""Call tracing with OpenTelemetry.

Every borrower turn is a span; inside it, each model call, tool call and reply check is a child
span with its own timing and attributes (model, tokens, cached tokens, queue wait, tool result,
guard refusal, replaced reply). Attribute names follow the OpenTelemetry GenAI conventions
(gen_ai.*) where one exists, kisht.* otherwise.

All turns of one call share one trace id, derived from the call id, so a whole conversation is
one trace even though its turns arrive as separate requests (voice) or separate CLI inputs.

Spans go to the insights store (the dashboard's call trace). Setting `tracing.otlp_endpoint`
in config.yaml also sends them to any OpenTelemetry backend (Jaeger, Arize Phoenix, Grafana
Tempo) with no code change. Without setup_tracing() every span is a no-op, so tests and tools
that do not care pay nothing.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags

from kisht.insights import InsightsStore

CALL_ID = "kisht.call_id"
_tracer = trace.get_tracer("kisht")


class InsightsSpanExporter(SpanExporter):
    """Writes finished spans to the insights store, indexed by call id."""

    def __init__(self, store: InsightsStore):
        self.store = store

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        rows = []
        for s in spans:
            attrs = {k: _plain(v) for k, v in (s.attributes or {}).items()}
            rows.append({
                "span_id": f"{s.context.span_id:016x}",
                "trace_id": f"{s.context.trace_id:032x}",
                "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                "call_id": attrs.get(CALL_ID),
                "name": s.name, "start_ns": s.start_time, "end_ns": s.end_time,
                "status": s.status.status_code.name, "attrs": attrs})
        self.store.add_spans(rows)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def _plain(v: Any) -> Any:
    return list(v) if isinstance(v, tuple) else v


def setup_tracing(store: InsightsStore, otlp_endpoint: str | None = None,
                  service_name: str = "kisht") -> TracerProvider:
    from opentelemetry.sdk.resources import Resource

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(InsightsSpanExporter(store)))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/traces")))
    global _tracer
    _tracer = provider.get_tracer("kisht")
    return provider


def trace_id_for(call_id: str) -> int:
    return int(hashlib.sha256(call_id.encode()).hexdigest()[:32], 16) or 1


def _call_context(call_id: str) -> otel_context.Context:
    parent = SpanContext(trace_id=trace_id_for(call_id),
                         span_id=int(hashlib.sha256((call_id + "/root").encode())
                                     .hexdigest()[:16], 16) or 1,
                         is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED))
    return trace.set_span_in_context(NonRecordingSpan(parent))


@contextmanager
def call_span(call_id: str, name: str, **attrs: Any) -> Iterator[trace.Span]:
    """A top-level span of a call (one turn, the greeting, the post-call review)."""
    with _tracer.start_as_current_span(name, context=_call_context(call_id)) as span:
        span.set_attribute(CALL_ID, call_id)
        set_attrs(span, **attrs)
        yield span


@contextmanager
def child_span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    """A step inside the current span; carries the same call id."""
    parent = trace.get_current_span()
    call_id = getattr(parent, "attributes", {}).get(CALL_ID) if parent else None
    with _tracer.start_as_current_span(name) as span:
        if call_id:
            span.set_attribute(CALL_ID, call_id)
        set_attrs(span, **attrs)
        yield span


def set_attrs(span: trace.Span, **attrs: Any) -> None:
    for k, v in attrs.items():
        if v is None:
            continue
        key = k.replace("__", ".")
        if isinstance(v, (dict, list)) and not (isinstance(v, list) and all(
                isinstance(x, str) for x in v)):
            v = json.dumps(v, ensure_ascii=False)
        span.set_attribute(key, v)


def mark_error(span: trace.Span, message: str) -> None:
    span.set_status(Status(StatusCode.ERROR, message))
