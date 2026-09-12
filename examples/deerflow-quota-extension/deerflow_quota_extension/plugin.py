"""The quota extension's contribution implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRuntimeDeps,
    MiddlewarePlacement,
    Placement,
    task_store_from_runtime,
)
from fastapi import APIRouter, Depends, HTTPException
from langchain.agents.middleware import AgentMiddleware


@dataclass
class RunQuota:
    """Task-scoped tool-call budget and usage for one lead run or subagent."""

    limit: int
    used: int = 0
    denied: int = 0


@dataclass
class QuotaTotals:
    """App-scoped aggregate folded in when each task stops."""

    runs: int = 0
    used: int = 0
    denied: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def absorb(self, quota: RunQuota | None) -> None:
        with self._lock:
            self.runs += 1
            if quota is not None:
                self.used += quota.used
                self.denied += quota.denied

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"runs": self.runs, "used": self.used, "denied": self.denied}


def _totals(app_store: ExtensionData) -> QuotaTotals:
    return app_store.get_or_init(QuotaTotals, QuotaTotals)


class QuotaMiddleware(AgentMiddleware):
    """Deny tool calls once a task exceeds its per-run budget."""

    def __init__(self, limit: int) -> None:
        self.limit = limit

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        store = task_store_from_runtime(getattr(request, "runtime", None))
        if store is not None:
            quota = store.get_or_init(RunQuota, lambda: RunQuota(limit=self.limit))
            if quota.used >= quota.limit:
                quota.denied += 1
                return f"Error: tool-call quota exceeded for this run ({quota.limit} calls allowed)."
            quota.used += 1
        return await handler(request)


class QuotaMiddlewareContributor:
    def __init__(self, limit: int) -> None:
        self.limit = limit

    def contribute_middlewares(
        self,
        app_store: ExtensionData,
        ctx: AgentBuildContext,
    ) -> Sequence[MiddlewarePlacement]:
        return (
            MiddlewarePlacement(
                QuotaMiddleware(self.limit),
                Placement.TOOL_VISIBLE,
                AgentScope.BOTH,
            ),
        )


class QuotaTaskLifecycle:
    async def on_task_start(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: object,
    ) -> None:
        return None

    async def on_task_stop(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: object,
        outcome: object,
    ) -> None:
        _totals(app_store).absorb(task_store.remove(RunQuota))


class QuotaService:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._deps: ExtensionRuntimeDeps | None = None

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._deps = deps

    async def stop(self) -> None:
        self._deps = None

    async def require_deps(self) -> ExtensionRuntimeDeps:
        deps = self._deps
        if deps is None or deps.app_store is None:
            raise HTTPException(status_code=503, detail="quota extension is not running")
        return deps


def build_router(service: QuotaService) -> APIRouter:
    """Build the stats route eagerly; runtime deps arrive later via the service."""
    router = APIRouter(prefix="/api/quota", tags=["quota"])

    @router.get("/stats")
    async def read_stats(
        deps: ExtensionRuntimeDeps = Depends(service.require_deps),
    ) -> dict[str, Any]:
        assert deps.app_store is not None
        return {"tool_calls_per_run": service.limit, **_totals(deps.app_store).snapshot()}

    return router
