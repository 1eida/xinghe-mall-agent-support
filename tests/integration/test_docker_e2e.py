import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from client import AgentClient

APP_PATH = (Path.cwd() / "src" / "streamlit_app.py").resolve()
ORDER_QUERY = "查询订单 ORD1001，手机号后四位 8821"


@pytest.mark.docker
def test_service_with_mock_customer_support():
    """Test the customer-support service using offline demo orders.

    Requires a running service with CUSTOMER_SUPPORT_MODE=mock; no API key is needed.
    """
    client = AgentClient(os.getenv("AGENT_URL", "http://127.0.0.1:8080"), agent="customer-support")
    response = client.invoke(ORDER_QUERY)
    assert response.type == "ai"
    assert "订单 ORD1001" in response.content
    assert "运输中" in response.content


@pytest.mark.docker
def test_service_with_app():
    """Test the service using the app.

    Requires a running service with CUSTOMER_SUPPORT_MODE=mock; no API key is needed.
    """
    at = AppTest.from_file(str(APP_PATH)).run()
    assert at.chat_message[0].avatar == "assistant"
    welcome = at.chat_message[0].markdown[0].value
    assert welcome.startswith("你好！我是电商智能客服演示助手。")
    assert not at.exception

    assert len(at.sidebar.selectbox) == 0
    at.chat_input[0].set_value(ORDER_QUERY).run()
    assert at.chat_message[0].avatar == "user"
    assert at.chat_message[0].markdown[0].value == ORDER_QUERY
    assert at.chat_message[1].avatar == "assistant"
    assert "订单 ORD1001" in at.chat_message[1].markdown[0].value
    assert "运输中" in at.chat_message[1].markdown[0].value
    assert not at.exception
