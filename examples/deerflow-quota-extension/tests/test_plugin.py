from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRegistry,
    ExtensionRuntimeDeps,
    HostPolicySnapshot,
    TaskInfo,
    TaskOutcome,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from deerflow_quota_extension import install


class FakeRegistry:
    def __init__(self) -> None:
        self.middleware_contributors: list[Any] = []
        self.task_lifecycle_contributors: list[Any] = []
        self.system_model_observers: list[Any] = []
        self.agent_assembly_observers: list[Any] = []
        self.context_compaction_observers: list[Any] = []
        self.services: list[Any] = []
        self.contributed_routers: list[Any] = []

    def middlewares(self, contributor: Any) -> None:
        self.middleware_contributors.append(contributor)

    def task_lifecycle(self, contributor: Any) -> None:
        self.task_lifecycle_contributors.append(contributor)

    def system_model_observer(self, observer: Any) -> None:
        self.system_model_observers.append(observer)

    def agent_assembly_observer(self, observer: Any) -> None:
        self.agent_assembly_observers.append(observer)

    def context_compaction_observer(self, observer: Any) -> None:
        self.context_compaction_observers.append(observer)

    def service(self, service: Any) -> None:
        self.services.append(service)

    def routers(self, routers: Any) -> None:
        self.contributed_routers.extend(routers)


@dataclass
class FakeRuntime:
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeToolRequest:
    runtime: FakeRuntime


def _tool_request(store: ExtensionData) -> FakeToolRequest:
    return FakeToolRequest(runtime=FakeRuntime(context={EXTENSION_TASK_STORE_KEY: store}))


def _task(task_id: str = "task-1") -> TaskInfo:
    return TaskInfo(task_id=task_id, run_id=f"run-{task_id}", thread_id=f"thread-{task_id}", kind="lead")


def _placement(registry: FakeRegistry, app_store: ExtensionData):
    return registry.middleware_contributors[0].contribute_middlewares(app_store, AgentBuildContext(scope=AgentScope.LEAD))[0]


def test_install_registers_the_expected_kinds() -> None:
    registry = FakeRegistry()

    install(registry, {})

    assert isinstance(registry, ExtensionRegistry)
    assert len(registry.middleware_contributors) == 1
    assert len(registry.task_lifecycle_contributors) == 1
    assert len(registry.services) == 1
    assert len(registry.contributed_routers) == 1
    assert [route.path for route in registry.contributed_routers[0].routes] == ["/api/quota/stats"]
    assert install.__deerflow_api__ == "0.2.0"
    assert install.__deerflow_name__ == "quota"


def test_disabled_extension_registers_nothing() -> None:
    registry = FakeRegistry()

    install(registry, {"enabled": False})

    assert registry.middleware_contributors == []
    assert registry.task_lifecycle_contributors == []
    assert registry.services == []
    assert registry.contributed_routers == []


def test_middleware_enforces_per_run_quota() -> None:
    registry = FakeRegistry()
    install(registry, {"tool_calls_per_run": 2})
    placement = _placement(registry, ExtensionData("app"))

    async def exercise() -> tuple[str, str, str, int]:
        handled = 0

        async def handler(_request: object) -> str:
            nonlocal handled
            handled += 1
            return "tool-result"

        task_store = ExtensionData("task-1")
        request = _tool_request(task_store)
        first = await placement.middleware.awrap_tool_call(request, handler)
        second = await placement.middleware.awrap_tool_call(request, handler)
        third = await placement.middleware.awrap_tool_call(request, handler)
        return first, second, third, handled

    first, second, third, handled = asyncio.run(exercise())

    assert (first, second) == ("tool-result", "tool-result")
    assert "quota exceeded" in third.lower()
    # The denied call must not reach the real tool.
    assert handled == 2


def test_quota_is_scoped_per_task() -> None:
    registry = FakeRegistry()
    install(registry, {"tool_calls_per_run": 1})
    placement = _placement(registry, ExtensionData("app"))

    async def exercise() -> tuple[str, str, str]:
        async def handler(_request: object) -> str:
            return "tool-result"

        task_a = ExtensionData("task-a")
        task_b = ExtensionData("task-b")
        a_first = await placement.middleware.awrap_tool_call(_tool_request(task_a), handler)
        b_first = await placement.middleware.awrap_tool_call(_tool_request(task_b), handler)
        a_second = await placement.middleware.awrap_tool_call(_tool_request(task_a), handler)
        return a_first, b_first, a_second

    a_first, b_first, a_second = asyncio.run(exercise())

    assert a_first == "tool-result"
    assert b_first == "tool-result"
    assert "quota exceeded" in a_second.lower()


def test_stats_route_reports_aggregate_usage() -> None:
    registry = FakeRegistry()
    install(registry, {"tool_calls_per_run": 2})
    app_store = ExtensionData("app")
    placement = _placement(registry, app_store)
    lifecycle = registry.task_lifecycle_contributors[0]

    async def exercise() -> tuple[int, int, dict[str, Any], int]:
        info = _task()
        task_store = ExtensionData("task-1")
        await lifecycle.on_task_start(app_store, task_store, info)

        async def handler(_request: object) -> str:
            return "tool-result"

        request = _tool_request(task_store)
        await placement.middleware.awrap_tool_call(request, handler)
        await placement.middleware.awrap_tool_call(request, handler)
        await placement.middleware.awrap_tool_call(request, handler)  # denied

        await lifecycle.on_task_stop(app_store, task_store, info, TaskOutcome.COMPLETED)

        app = FastAPI()
        app.include_router(registry.contributed_routers[0])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            before_start = await client.get("/api/quota/stats")
            await registry.services[0].start(
                ExtensionRuntimeDeps(
                    app_store=app_store,
                    policy=HostPolicySnapshot(max_subagents_per_run=6),
                    session_factory=object(),
                )
            )
            response = await client.get("/api/quota/stats")
            await registry.services[0].stop()
            after_stop = await client.get("/api/quota/stats")
        return before_start.status_code, response.status_code, response.json(), after_stop.status_code

    before_start, status_code, body, after_stop = asyncio.run(exercise())

    assert before_start == 503
    assert status_code == 200
    assert after_stop == 503
    assert body == {
        "tool_calls_per_run": 2,
        "runs": 1,
        "used": 2,
        "denied": 1,
    }
