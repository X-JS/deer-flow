"""A standalone DeerFlow extension that enforces a per-run tool-call quota."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_quota_extension.plugin import (
    QuotaMiddlewareContributor,
    QuotaService,
    QuotaTaskLifecycle,
    build_router,
)

__all__ = ["install"]


@extension(api="0.2.0", name="quota")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register the quota middleware, lifecycle hook, service, and stats route."""
    if config.get("enabled", True) is False:
        return

    limit = int(config.get("tool_calls_per_run", 50))
    service = QuotaService(limit)
    registry.middlewares(QuotaMiddlewareContributor(limit))
    registry.task_lifecycle(QuotaTaskLifecycle())
    registry.service(service)
    registry.routers((build_router(service),))


_entry_point: ExtensionInstall = install
