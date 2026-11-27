"""
Agentgateway MCP client for react-agent.
Invokes downstream tools via agentgateway over HTTP using RFC 8693 exchanged Bearer token.
"""

import json
import requests
from typing import Dict, Any, Optional

AGENTGATEWAY_URL = "http://localhost:8088/mcp"
PROTOCOL_VERSION = "2026-07-28"


def call_mcp_tool(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    bearer_token: Optional[str] = None,
    gateway_url: str = AGENTGATEWAY_URL,
    client_name: str = "react-agent",
) -> Dict[str, Any]:
    """
    Invokes an MCP tool on Agentgateway using the modern protocol with Bearer token authentication.
    """
    if arguments is None:
        arguments = {}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL_VERSION,
        "mcp-method": "tools/call",
        "mcp-name": tool_name,
    }

    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientInfo": {
                    "name": client_name,
                    "version": "1.0",
                },
                "io.modelcontextprotocol/clientCapabilities": {},
            },
            "name": tool_name,
            "arguments": arguments,
        },
    }

    response = requests.post(gateway_url, headers=headers, json=body, timeout=10)
    
    # Process event-stream or json response
    content_type = response.headers.get("Content-Type", "")
    text = response.text

    parsed_result = None
    if "text/event-stream" in content_type:
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    parsed_result = json.loads(line[6:])
                    break
                except json.JSONDecodeError:
                    pass
    elif content_type.startswith("application/json"):
        try:
            parsed_result = response.json()
        except json.JSONDecodeError:
            pass

    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "data": parsed_result,
        "raw_text": text,
    }
