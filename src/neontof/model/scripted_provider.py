"""Deterministic scripted provider for model-invocation tests."""

from __future__ import annotations

from collections.abc import Sequence
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


class _ScriptedProvider:
    def __init__(self, steps: tuple[ProviderStep, ...]) -> None:
        self._steps = steps
        self._next_step_index = 0
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
        if self._next_step_index >= len(self._steps):
            self._append_call(
                request,
                status="rejected",
                usage=None,
                error_code="script_exhausted",
            )
            raise RuntimeError("script exhausted")

        step = self._steps[self._next_step_index]
        self._next_step_index += 1
        if isinstance(step, SuccessStep):
            self._append_call(
                request,
                status="succeeded",
                usage=step.response.usage,
                error_code=None,
            )
            return step.response
        if isinstance(step, ModelErrorStep):
            self._append_call(
                request,
                status="failed",
                usage=None,
                error_code="model_error",
            )
            raise RuntimeError("model invocation failed")  # noqa: TRY004
        if isinstance(step, TimeoutStep):
            self._append_call(
                request,
                status="timed_out",
                usage=None,
                error_code="timeout",
            )
            raise TimeoutError("model invocation timed out")
        if isinstance(step, InvalidJsonStep):
            self._append_call(
                request,
                status="rejected",
                usage=None,
                error_code="invalid_json",
            )
            raise ValueError("model response JSON is invalid")  # noqa: TRY004
        raise RuntimeError("script exhausted")

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]:
        return tuple(self._calls)


def create_scripted_provider(steps: Sequence[ProviderStep]) -> TestProvider:
    """Create a provider that consumes one scripted step per invocation."""

    return _ScriptedProvider(tuple(steps))


__all__ = ("create_scripted_provider",)
