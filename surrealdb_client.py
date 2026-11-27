"""
SurrealDB Agentgateway Client for react-agent.
Interacts with Agentgateway to run queries against SurrealDB via RFC 8693 delegation.
"""

import json
from typing import Dict, Any, Optional
from agentgateway_client import call_mcp_tool


def execute_surreal_agent_task(
    query: str,
    user_token: str,
    tool_name: str = "surrealdb_surrealdb_query",
    gateway_url: str = "http://localhost:8088/mcp",
) -> Dict[str, Any]:
    """
    Calls SurrealDB query tool via Agentgateway MCP endpoint.
    Transmits user token in Authorization header and tool arguments.
    """
    return call_mcp_tool(
        tool_name=tool_name,
        arguments={"query": query, "inbound_token": user_token},
        bearer_token=user_token,
        gateway_url=gateway_url,
        client_name="react-agent",
    )
