"""
End-to-End Integration & Security Test Suite:
Keycloak 26 RFC 8693 Token Exchange, SPIFFE/SPIRE SVID Attestation, and MCP Tool Delegation.
"""

import time
import json
import base64
import requests
import pytest
from spire_client import fetch_agent_svid, check_spire_socket
from keycloak_exchange import exchange_user_token

KEYCLOAK_URL = "http://localhost:8082"
REALM = "myrealm"
MCP_URL = "http://localhost:9998"


def get_user_token(username="alice", password="password123"):
    """Helper to authenticate a human user and obtain an initial access token."""
    res = requests.post(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "client_id": "user-client",
            "username": username,
            "password": password,
            "grant_type": "password"
        },
        timeout=5
    )
    assert res.status_code == 200, f"User authentication failed: {res.text}"
    return res.json()["access_token"]


def decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    assert len(parts) >= 2
    segment = parts[1]
    rem = len(segment) % 4
    if rem > 0:
        segment += "=" * (4 - rem)
    return json.loads(base64.urlsafe_b64decode(segment.encode()).decode())


# ==============================================================================
# 1. SPIFFE/SPIRE Workload Attestation Tests
# ==============================================================================

def test_spire_workload_attestation():
    """Verify react-agent connects to Workload API socket and retrieves valid SVID."""
    assert check_spire_socket(), "SPIRE socket must be present"
    svid_data = fetch_agent_svid(output_dir="/tmp")
    assert svid_data["spiffe_id"] == "spiffe://example.org/workload/react-agent"
    assert "svid.0.pem" in svid_data["cert_path"]
    assert "svid.0.key" in svid_data["key_path"]


# ==============================================================================
# 2. Keycloak RFC 8693 Token Exchange Tests
# ==============================================================================

def test_keycloak_rfc8693_token_exchange():
    """
    Test RFC 8693 Token Exchange against Keycloak 26:
    The agent exchanges user token for a downstream token with audience api://my-mcp-server
    and actor delegation ('act': {'sub': 'react-agent'}).
    """
    user_token = get_user_token()
    exchange_result = exchange_user_token(subject_token=user_token)

    assert exchange_result["status_code"] == 200, f"Exchange failed: {exchange_result}"
    token_data = exchange_result["response"]
    assert "access_token" in token_data
    assert token_data.get("token_type") == "Bearer"
    assert token_data.get("issued_token_type") == "urn:ietf:params:oauth:token-type:access_token"

    claims = decode_jwt_payload(token_data["access_token"])
    # Audience assertion
    aud = claims.get("aud")
    if isinstance(aud, list):
        assert "api://my-mcp-server" in aud
    else:
        assert aud == "api://my-mcp-server"

    # Actor claim assertion
    assert "act" in claims, "Exchanged token must contain 'act' delegation claim"
    assert claims["act"].get("sub") == "react-agent"

    # Scope assertion
    full_scopes = f"{claims.get('scope', '')} {claims.get('scp', '')}"
    assert "mcp.tools.execute" in full_scopes


# ==============================================================================
# 3. Downstream MCP Server Tool Execution
# ==============================================================================

def test_mcp_server_positive_tool_call():
    """
    Full end-to-end flow:
    1. Agent retrieves user token and exchanges via Keycloak RFC 8693.
    2. Agent presents exchanged token to downstream MCP server.
    3. MCP server verifies audience, scope, and actor, executing tool with isError: false.
    """
    user_token = get_user_token()
    exchange_result = exchange_user_token(subject_token=user_token)
    assert exchange_result["status_code"] == 200
    exchanged_token = exchange_result["response"]["access_token"]

    tool_call_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "read_financial_report",
            "arguments": {"quarter": "Q4"}
        },
        "id": 1
    }

    mcp_res = requests.post(
        f"{MCP_URL}/mcp",
        headers={"Authorization": f"Bearer {exchanged_token}"},
        json=tool_call_payload,
        timeout=5
    )
    assert mcp_res.status_code == 200, f"MCP tool execution failed: {mcp_res.text}"
    mcp_data = mcp_res.json()
    assert mcp_data.get("result", {}).get("isError") is False
    content_text = mcp_data["result"]["content"][0]["text"]
    assert "read_financial_report" in content_text
    assert "react-agent" in content_text


# ==============================================================================
# 4. Security Regressions & Negative Vectors
# ==============================================================================

def test_missing_token_rejection():
    """Unauthenticated call to MCP server fails with 401."""
    res = requests.post(f"{MCP_URL}/mcp", json={"method": "tools/call", "id": 1}, timeout=5)
    assert res.status_code == 401


def test_audience_mismatch_rejection():
    """Token with mismatched audience must be rejected by MCP server with 403."""
    user_token = get_user_token()
    # Direct user token has aud 'react-agent' / 'account', not 'api://my-mcp-server'
    res = requests.post(
        f"{MCP_URL}/mcp",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"method": "tools/call", "id": 1},
        timeout=5
    )
    assert res.status_code == 403
    assert "audience mismatch" in res.json().get("detail", "").lower()


def test_invalid_client_credentials_rejection():
    """Token exchange with invalid client secret is rejected by Keycloak with 400/401."""
    user_token = get_user_token()
    res = exchange_user_token(subject_token=user_token, client_secret="wrong-secret")
    assert res["status_code"] in (400, 401)
    error = res["response"].get("error") if isinstance(res["response"], dict) else ""
    assert error in ("unauthorized_client", "invalid_client")


def test_expired_subject_token_rejection():
    """Token exchange with malformed or expired token is rejected with invalid_grant."""
    res = exchange_user_token(subject_token="header.expired_or_invalid_payload.signature")
    assert res["status_code"] == 400
    error = res["response"].get("error") if isinstance(res["response"], dict) else ""
    assert error in ("invalid_grant", "invalid_request")
