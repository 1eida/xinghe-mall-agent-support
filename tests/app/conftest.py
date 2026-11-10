from unittest.mock import patch

import pytest

from schema import AgentInfo, ServiceMetadata


@pytest.fixture
def mock_agent_client(mock_env):
    """Fixture for creating a mock AgentClient with a clean environment."""

    mock_info = ServiceMetadata(
        default_agent="customer-support",
        agents=[
            AgentInfo(key="customer-support", description="Customer support"),
        ],
        default_model="mock",
        models=["mock"],
    )

    with patch("client.AgentClient") as mock_agent_client:
        mock_agent_client_instance = mock_agent_client.return_value
        mock_agent_client_instance.info = mock_info
        mock_agent_client_instance.agent = "customer-support"
        yield mock_agent_client_instance
