import logging
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from schema import AgentInfo


@pytest.mark.asyncio
async def test_lifespan(monkeypatch, caplog) -> None:
    """Test that the lifespan sets up the database, loads the agents, and logs errors."""
    from service import service

    fake_saver_setup = False

    class FakeSaver:
        async def setup(self) -> None:
            nonlocal fake_saver_setup
            fake_saver_setup = True

    fake_saver = FakeSaver()

    @asynccontextmanager
    async def fake_initialize_database():
        yield fake_saver

    agents = {
        "good": type("Agent", (), {"checkpointer": None})(),
        "bad": type("Agent", (), {"checkpointer": None})(),
    }

    async def fake_load_agent(agent_key: str) -> None:
        if agent_key == "bad":
            raise RuntimeError("boom")

    def fake_get_agent(agent_key: str):
        return agents[agent_key]

    monkeypatch.setattr(service, "initialize_database", fake_initialize_database)
    monkeypatch.setattr(service, "load_agent", fake_load_agent)
    monkeypatch.setattr(service, "get_agent", fake_get_agent)
    monkeypatch.setattr(
        service,
        "get_all_agent_info",
        lambda: [
            AgentInfo(key="good", description=""),
            AgentInfo(key="bad", description=""),
        ],
    )

    caplog.set_level(logging.INFO, logger=service.logger.name)

    async with service.lifespan(FastAPI()):
        pass

    assert fake_saver_setup
    assert agents["good"].checkpointer is fake_saver
    assert agents["bad"].checkpointer is fake_saver

    assert "Agent loaded: good" in caplog.text
    assert "Failed to load agent bad: boom" in caplog.text


@pytest.mark.asyncio
async def test_sqlite_restores_pending_ticket_and_history_after_reopen(tmp_path, monkeypatch):
    import sqlite3

    from langchain_core.messages import HumanMessage

    import customer_support.store as business_store
    import memory
    from agents.customer_support_mock import builder

    business_path = tmp_path / "orders.db"
    monkeypatch.setattr(business_store, "DEFAULT_DB_PATH", business_path)
    monkeypatch.setattr(
        memory.settings, "SQLITE_DB_PATH", str(tmp_path / "state" / "checkpoint.db")
    )
    config = {"configurable": {"thread_id": "persisted-support-thread"}}

    async with memory.initialize_database() as saver:
        await saver.setup()
        graph = builder.compile(checkpointer=saver)
        first = await graph.ainvoke(
            {"messages": [HumanMessage(content="为 ORD1001 创建工单，手机号后四位 8821")]},
            config=config,
        )
        assert "请回复“确认”" in first["messages"][-1].content

    with sqlite3.connect(business_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0] == 0

    # A fresh saver and graph simulate the service restarting before confirmation.
    async with memory.initialize_database() as saver:
        await saver.setup()
        graph = builder.compile(checkpointer=saver)
        restored = await graph.aget_state(config)
        assert restored.values["pending_ticket"]["order_id"] == "ORD1001"
        assert len(restored.values["messages"]) == 2
        confirmed = await graph.ainvoke({"messages": [HumanMessage(content="确认")]}, config=config)
        assert "工单已创建" in confirmed["messages"][-1].content
        assert confirmed["pending_ticket"] is None
        assert len(confirmed["messages"]) == 4

    with sqlite3.connect(business_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0] == 1
