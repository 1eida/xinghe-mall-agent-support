from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from streamlit.testing.v1 import AppTest

from client import AgentClientError
from schema import ChatHistory, ChatMessage

APP_PATH = (Path.cwd() / "src" / "streamlit_app.py").resolve()


def test_app_simple_non_streaming(mock_agent_client):
    """Test the full app - happy path"""
    at = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    WELCOME_START = "你好！我是电商智能客服演示助手。"
    PROMPT = "Know any jokes?"
    RESPONSE = "Sure! Here's a joke:"

    mock_agent_client.ainvoke = AsyncMock(
        return_value=ChatMessage(type="ai", content=RESPONSE),
    )

    assert at.chat_message[0].avatar == "assistant"
    assert at.chat_message[0].markdown[0].value.startswith(WELCOME_START)

    at.sidebar.toggle[0].set_value(False)  # Use Streaming = False
    at.chat_input[0].set_value(PROMPT).run()
    assert at.chat_message[0].avatar == "user"
    assert at.chat_message[0].markdown[0].value == PROMPT
    assert at.chat_message[1].avatar == "assistant"
    assert at.chat_message[1].markdown[0].value == RESPONSE
    assert not at.exception


def test_app_settings(mock_agent_client):
    """Test the full app - happy path"""
    at = AppTest.from_file(str(APP_PATH))
    at.query_params["user_id"] = "1234"
    at.run()

    PROMPT = "Know any jokes?"
    RESPONSE = "Sure! Here's a joke:"

    mock_agent_client.ainvoke = AsyncMock(
        return_value=ChatMessage(type="ai", content=RESPONSE),
    )

    at.sidebar.toggle[0].set_value(False)  # Use Streaming = False
    assert len(at.sidebar.selectbox) == 0
    at.chat_input[0].set_value(PROMPT).run()

    # Basic checks
    assert at.chat_message[0].avatar == "user"
    assert at.chat_message[0].markdown[0].value == PROMPT
    assert at.chat_message[1].avatar == "assistant"
    assert at.chat_message[1].markdown[0].value == RESPONSE

    # Check the args match the settings
    assert mock_agent_client.agent == "customer-support"
    mock_agent_client.ainvoke.assert_called_with(
        message=PROMPT,
        thread_id=at.session_state.thread_id,
        user_id="1234",
    )
    assert not at.exception


def test_app_thread_id_history(mock_agent_client):
    """Test the thread_id is generated"""

    at = AppTest.from_file(str(APP_PATH)).run()

    # Reset and set thread_id
    at = AppTest.from_file(str(APP_PATH))
    at.query_params["thread_id"] = "1234"
    HISTORY = [
        ChatMessage(type="human", content="What is the weather?"),
        ChatMessage(type="ai", content="The weather is sunny."),
    ]
    mock_agent_client.get_history.return_value = ChatHistory(messages=HISTORY)
    at.run()
    assert at.session_state.thread_id == "1234"
    mock_agent_client.get_history.assert_called_with(thread_id="1234")
    assert at.chat_message[0].avatar == "user"
    assert at.chat_message[0].markdown[0].value == "What is the weather?"
    assert at.chat_message[1].avatar == "assistant"
    assert at.chat_message[1].markdown[0].value == "The weather is sunny."
    assert not at.exception


@pytest.mark.asyncio
async def test_app_streaming(mock_agent_client):
    """Test the app with streaming enabled - including tool messages"""
    at = AppTest.from_file(str(APP_PATH)).run()

    # Setup mock streaming response
    PROMPT = "What is 6 * 7?"
    ai_with_tool = ChatMessage(
        type="ai",
        content="",
        tool_calls=[{"name": "calculator", "id": "test_call_id", "args": {"expression": "6 * 7"}}],
    )
    tool_message = ChatMessage(type="tool", content="42", tool_call_id="test_call_id")
    final_ai_message = ChatMessage(type="ai", content="The answer is 42")

    messages = [ai_with_tool, tool_message, final_ai_message]

    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for m in messages:
            yield m

    mock_agent_client.astream = Mock(return_value=amessage_iter())

    at.toggle[0].set_value(True)  # Use Streaming = True
    at.chat_input[0].set_value(PROMPT).run()

    assert at.chat_message[0].avatar == "user"
    assert at.chat_message[0].markdown[0].value == PROMPT
    response = at.chat_message[1]
    tool_status = response.status[0]
    assert response.avatar == "assistant"
    assert tool_status.label == "🛠️ Tool Call: calculator"
    assert tool_status.icon == ":material/check:"
    assert tool_status.markdown[0].value == "Input:"
    assert tool_status.json[0].value == '{"expression": "6 * 7"}'
    assert tool_status.markdown[1].value == "Output:"
    assert tool_status.markdown[2].value == "42"
    assert response.markdown[-1].value == "The answer is 42"
    assert not at.exception


@pytest.mark.asyncio
async def test_app_streaming_hitl_interrupt_without_tool_result(mock_agent_client):
    """A tool call paused by HITL must render the approval prompt without crashing."""
    at = AppTest.from_file(str(APP_PATH)).run()

    prompt = "Create a support ticket"
    ai_with_tool = ChatMessage(
        type="ai",
        content="",
        tool_calls=[
            {
                "name": "create_support_ticket",
                "id": "ticket_call_id",
                "args": {"order_id": "ORD1001"},
            }
        ],
    )
    interrupt_message = ChatMessage(
        type="ai",
        content="请回复“确认”执行，或回复“取消”。",
    )

    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for message in [ai_with_tool, interrupt_message]:
            yield message

    mock_agent_client.astream = Mock(return_value=amessage_iter())

    at.toggle[0].set_value(True)
    at.chat_input[0].set_value(prompt).run()

    response = at.chat_message[1]
    assert response.status[0].label == "⏸️ Waiting for approval: create_support_ticket"
    assert response.markdown[-1].value == "请回复“确认”执行，或回复“取消”。"
    assert not at.exception


@pytest.mark.asyncio
async def test_app_streaming_standalone_tool_result_after_hitl_resume(mock_agent_client):
    """A resumed HITL run may start with a ToolMessage before the final AI reply."""
    at = AppTest.from_file(str(APP_PATH)).run()

    prompt = "确认"
    tool_message = ChatMessage(
        type="tool",
        content='{"ok": true, "ticket_id": "TKT-001"}',
        tool_call_id="ticket_call_id",
    )
    final_ai_message = ChatMessage(type="ai", content="工单已创建，编号为 TKT-001。")

    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for message in [tool_message, final_ai_message]:
            yield message

    mock_agent_client.astream = Mock(return_value=amessage_iter())

    at.toggle[0].set_value(True)
    at.chat_input[0].set_value(prompt).run()

    response = at.chat_message[1]
    assert response.status[0].label == "🛠️ Tool result"
    assert response.markdown[-1].value == "工单已创建，编号为 TKT-001。"
    assert not at.exception


@pytest.mark.asyncio
async def test_app_init_error(mock_agent_client):
    """Test the app with an error in the agent initialization"""
    at = AppTest.from_file(str(APP_PATH)).run()

    # Setup mock streaming response
    PROMPT = "What is 6 * 7?"
    mock_agent_client.astream.side_effect = AgentClientError("Error connecting to agent")

    at.toggle[0].set_value(True)  # Use Streaming = True
    at.chat_input[0].set_value(PROMPT).run()

    assert at.chat_message[0].avatar == "assistant"
    assert at.chat_message[1].avatar == "user"
    assert at.chat_message[1].markdown[0].value == PROMPT
    assert at.error[0].value == "Error generating response: Error connecting to agent"
    assert not at.exception


def test_app_new_chat_btn(mock_agent_client):
    at = AppTest.from_file(str(APP_PATH)).run()
    thread_id_a = at.session_state.thread_id

    at.sidebar.button[0].click().run()

    assert at.session_state.thread_id != thread_id_a
    assert not at.exception


def test_app_share_resume_dialog(mock_agent_client):
    """The share dialog uses the public Streamlit context and includes the thread ID."""
    at = AppTest.from_file(str(APP_PATH)).run()

    at.sidebar.button[-1].click().run()

    assert any(at.session_state.thread_id in markdown.value for markdown in at.markdown)
    assert not at.exception
