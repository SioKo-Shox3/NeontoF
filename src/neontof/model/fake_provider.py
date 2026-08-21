"""Deterministic fake model provider for focused tests."""

from __future__ import annotations

from typing import Literal

from neontof.model.model_invoker import (
    InvalidJsonStep,
    ModelErrorStep,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCallLogMeta,
    ProviderStep,
    SuccessStep,
    TimeoutStep,
)
from neontof.model.recorded_fixture import (
    SanitizedProviderCallLogEntry,
    TestProvider,
    sanitize_provider_call_log,
)


class _FakeProvider:
    def __init__(self, step: ProviderStep) -> None:
        self._step = step
        self._calls: list[SanitizedProviderCallLogEntry] = []

    def _append_call(
        self,
        request: ModelRequest,
        *,
        status: Literal["succeeded", "failed", "timed_out", "rejected"],
        usage: ModelUsage | None,
        error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None,
    ) -> None:
        meta = ProviderCallLogMeta(
            attempt=len(self._calls) + 1,
            status=status,
            usage=usage,
            context_item_count=len(request.context),
            error_code=error_code,
        )
        self._calls.append(sanitize_provider_call_log(request, meta))

    def invoke(self, request: ModelRequest) -> ModelResponse:
        if isinstance(self._step, SuccessStep):
            self._append_call(
                request,
                status="succeeded",
                usage=self._step.response.usage,
                error_code=None,
            )
            return self._step.response
        if isinstance(self._step, ModelErrorStep):
            self._append_call(
                request,
                status="failed",
                usage=None,
                error_code="model_error",
            )
            raise RuntimeError("model invocation failed")  # noqa: TRY004
        if isinstance(self._step, TimeoutStep):
            self._append_call(
                request,
                status="timed_out",
                usage=None,
                error_code="timeout",
            )
            raise TimeoutError("model invocation timed out")
        if isinstance(self._step, InvalidJsonStep):
            self._append_call(
                request,
                status="rejected",
                usage=None,
                error_code="invalid_json",
            )
            raise ValueError("model response JSON is invalid")  # noqa: TRY004
        raise AssertionError("unreachable provider step")

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]:
        return tuple(self._calls)


def create_fake_provider(step: ProviderStep) -> TestProvider:
    """Create a provider that repeats one validated step for every invocation."""

    return _FakeProvider(step)


__all__ = ("create_fake_provider",)
