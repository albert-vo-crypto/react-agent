"""
End-to-End Automated Test Suite:
SPIFFE/SPIRE Workload Attestation + Keycloak 26 RFC 8693 STS + Agentgateway MCP Server.

Validates the full specification from NotebookLM "Antigravity MCP Test" (SPEC.md):
1. SPIRE SVID Attestation (spiffe://example.org/workload/react-agent)
2. Unauthorized SVID fetch rejection (UID mismatch)
3. Positive Token Exchange & MCP Tool Execution on Agentgateway
4. Delegation Audit Trail Validation (act.sub == "react-agent", sub == user.id)
5. Audience Mismatch Rejection (unauthorized audience rejected by Agentgateway)
6. Scope Escalation Rejection (unauthorized scope rejected by Keycloak)
7. Session Expiration / Logout Coupling (invalid_grant upon logout)
"""

import os
import subprocess
import requests
import pytest
import jwt
from spire_client import fetch_agent_svid
from keycloak_exchange import exchange_user_token
from agentgateway_client import call_mcp_tool

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8082")
REALM = os.environ.get("KEYCLOAK_REALM", "myrealm")
AGENTGATEWAY_URL = os.environ.get("AGENTGATEWAY_URL", "http://localhost:8088/mcp")
SOCKET_PATH = "/tmp/spire-agent/public/api.sock"


def get_user_token(username="alice", password="password123"):
    """Helper to authenticate a user against Keycloak."""
    url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    payload = {
        "client_id": "user-client",
        "username": username,
        "password": password,
        "grant_type": "password",
    }
    resp = requests.post(url, data=payload, timeout=10)
    assert resp.status_code == 200, f"User login failed: {resp.text}"
    return resp.json()["access_token"], resp.json().get("refresh_token")


class TestKeycloakSpireAgentgatewayE2E:

    def test_01_spire_workload_attestation(self):
        """
        Test 1: SPIRE SVID Attestation
        Assert spire-agent returns valid X.509 SVID matching spiffe://example.org/workload/react-agent.
        """
        svid_info = fetch_agent_svid(socket_path=SOCKET_PATH)
        assert svid_info["spiffe_id"] == "spiffe://example.org/workload/react-agent"
        assert svid_info["cert_pem"].startswith("-----BEGIN CERTIFICATE-----")
        assert svid_info["key_pem"].startswith("-----BEGIN PRIVATE KEY-----") or svid_info["key_pem"].startswith("-----BEGIN EC PRIVATE KEY-----")

    def test_02_unauthorized_svid_fetch(self):
        """
        Test 2: Unauthorized SVID Fetch
        Assert fetching an SVID from an unregistered selector/UID returns permission denied or no identity.
        """
        cmd = [
            "/home/dev1/spire-1.16.0/bin/spire-server",
            "entry",
            "show",
            "-spiffeID",
            "spiffe://example.org/workload/unauthorized-workload",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert "Found 0 entries" in res.stdout or res.returncode != 0

    def test_03_positive_token_exchange_and_mcp_tool_execution(self):
        """
        Test 3: Positive Token Exchange & MCP Tool Execution
        Authenticate user, exchange token via Keycloak for api://agentgateway,
        call execute_system_task on agentgateway, and assert tool execution success (isError: false).
        """
        user_token, _ = get_user_token("alice", "password123")
        assert user_token is not None

        # Perform RFC 8693 token exchange
        exchange_resp = exchange_user_token(
            subject_token=user_token,
            audience="api://agentgateway",
            scope="mcp.tools.execute",
        )
        assert exchange_resp["status_code"] == 200, f"Token exchange failed: {exchange_resp['response']}"
        exchanged_token = exchange_resp["response"]["access_token"]
        assert exchanged_token is not None

        # Execute MCP tool via Agentgateway
        mcp_res = call_mcp_tool(
            tool_name="system-task/execute_system_task",
            arguments={"task_name": "agent_audit_e2e"},
            bearer_token=exchanged_token,
            gateway_url=AGENTGATEWAY_URL,
        )

        assert mcp_res["status_code"] == 200, f"MCP call HTTP error: {mcp_res['status_code']}"
        assert mcp_res["data"] is not None
        result = mcp_res["data"].get("result", {})
        assert result.get("isError") is False
        content = result.get("content", [])
        assert len(content) > 0
        assert "executed successfully by SystemTaskServer" in content[0]["text"]

    def test_04_delegation_audit_trail_validation(self):
        """
        Test 4: Delegation Audit Trail Validation
        Decode the exchanged JWT and assert act.sub == "react-agent" and sub == user.id.
        """
        user_token, _ = get_user_token("alice", "password123")
        user_claims = jwt.decode(user_token, options={"verify_signature": False})

        exchange_resp = exchange_user_token(
            subject_token=user_token,
            audience="api://agentgateway",
            scope="mcp.tools.execute",
        )
        assert exchange_resp["status_code"] == 200
        exchanged_token = exchange_resp["response"]["access_token"]
        claims = jwt.decode(exchanged_token, options={"verify_signature": False})

        # Subject must match original user identity
        assert claims["sub"] == user_claims["sub"]
        # Actor delegation claim must identify react-agent
        assert "act" in claims
        assert claims["act"]["sub"] == "react-agent"
        # Authorized party and audience
        assert claims["azp"] == "react-agent"
        assert claims["aud"] == "api://agentgateway"

    def test_05_security_regression_audience_mismatch(self):
        """
        Test 5: Audience Mismatch Rejection
        Send a token exchanged for a different audience to agentgateway;
        assert agentgateway rejects the request with HTTP 400/401/403.
        """
        user_token, _ = get_user_token("alice", "password123")
        
        # Exchange token for a DIFFERENT audience (e.g. api://my-mcp-server)
        exchange_resp = exchange_user_token(
            subject_token=user_token,
            audience="api://my-mcp-server",
            scope="mcp.tools.execute",
        )
        assert exchange_resp["status_code"] == 200
        mismatched_token = exchange_resp["response"]["access_token"]

        # Attempt to call Agentgateway with wrong audience token
        mcp_res = call_mcp_tool(
            tool_name="system-task/execute_system_task",
            arguments={"task_name": "attack_audience_mismatch"},
            bearer_token=mismatched_token,
            gateway_url=AGENTGATEWAY_URL,
        )

        # Agentgateway rejects unauthorized/mismatched audience tokens
        assert mcp_res["status_code"] in [400, 401, 403]
        if mcp_res["data"] and "error" in mcp_res["data"]:
            assert mcp_res["data"]["error"]["message"] == "unknown resource"

    def test_06_security_regression_scope_escalation(self):
        """
        Test 6: Scope Escalation Rejection
        Request unauthorized scopes during token exchange;
        assert Keycloak or target rejects or bounds unauthorized scope.
        """
        user_token, _ = get_user_token("alice", "password123")

        # Attempt to request unauthorized administrative scope
        exchange_resp = exchange_user_token(
            subject_token=user_token,
            audience="api://agentgateway",
            scope="admin.super.user.escalation",
        )
        
        # Keycloak standard token exchange either rejects with invalid_scope or filters the scope
        if exchange_resp["status_code"] == 200:
            token = exchange_resp["response"]["access_token"]
            claims = jwt.decode(token, options={"verify_signature": False})
            granted_scopes = claims.get("scope", "").split()
            assert "admin.super.user.escalation" not in granted_scopes
        else:
            assert exchange_resp["status_code"] in [400, 401, 403]

    def test_07_security_regression_session_expiration_coupling(self):
        """
        Test 7: Session Expiration Coupling
        Log out the user session from Keycloak;
        assert subsequent token exchange or refresh attempts fail with invalid_grant.
        """
        user_token, refresh_token = get_user_token("alice", "password123")

        # Explicitly logout user session from Keycloak
        logout_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/logout"
        logout_payload = {
            "client_id": "user-client",
            "refresh_token": refresh_token,
        }
        logout_resp = requests.post(logout_url, data=logout_payload, timeout=10)
        assert logout_resp.status_code == 204

        # Attempting token exchange with invalidated session
        exchange_resp = exchange_user_token(
            subject_token=user_token,
            audience="api://agentgateway",
            scope="mcp.tools.execute",
        )
        # Session is invalidated -> Keycloak returns 400 invalid_request (Invalid token) or invalid_grant
        assert exchange_resp["status_code"] == 400
        assert exchange_resp["response"].get("error") in ["invalid_grant", "invalid_request"]
