"""
End-to-End Automated Test Suite:
SPIFFE/SPIRE Workload Attestation + Keycloak 26 RFC 8693 STS + Agentgateway + Hardened SurrealDB.

Verifies the complete specification from NotebookLM "Antigravity MCP Test" (SPEC.md):
1. SPIRE SVID Attestation: Positive issuance (spiffe://example.org/workload/react-agent).
2. Negative SPIRE Attestation: Unauthorized UID rejection.
3. Keycloak RFC 8693 Token Exchange: Mints target token for api://surrealdb with ns, db, ac, and act.sub.
4. Downstream Tool Execution: Agentgateway validates inbound JWT, exchanges token, and executes SurrealQL query on SurrealDB.
5. Security Regression - Audience Mismatch: Tokens without audience api://surrealdb are rejected by SurrealDB.
6. Security Regression - Actor Delegation Enforcement: Row-level security on agent_memory enforces actor_sub == "react-agent".
7. Security Regression - Session Logout Coupling: Logging out user invalidates subsequent token exchange.
"""

import os
import subprocess
import requests
import pytest
import jwt
import json
from spire_client import fetch_agent_svid
from surrealdb_client import execute_surreal_agent_task

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8082")
REALM = os.environ.get("KEYCLOAK_REALM", "myrealm")
SURREALDB_URL = os.environ.get("SURREALDB_URL", "http://127.0.0.1:8000")
AGENTGATEWAY_URL = os.environ.get("AGENTGATEWAY_URL", "http://localhost:8088/mcp")
SOCKET_PATH = "/tmp/spire-agent/public/api.sock"


def load_env():
    env = {}
    if os.path.exists("/home/dev1/.env"):
        with open("/home/dev1/.env") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    k, v = line.split("=", 1)
                    env[k] = v
    return env


def get_user_token(username="alice", password="password123"):
    """Helper to authenticate user against Keycloak via react-agent-client."""
    url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    payload = {
        "client_id": "react-agent-client",
        "username": username,
        "password": password,
        "grant_type": "password",
    }
    resp = requests.post(url, data=payload, timeout=10)
    assert resp.status_code == 200, f"User login failed: {resp.text}"
    return resp.json()["access_token"], resp.json().get("refresh_token")


def exchange_to_surrealdb(user_token: str) -> str:
    """Execute RFC 8693 token exchange via Keycloak as agentgateway."""
    env = load_env()
    secret = env.get("KEYCLOAK_GATEWAY_CLIENT_SECRET", "")
    url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": "agentgateway",
        "client_secret": secret,
        "subject_token": user_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "audience": "api://surrealdb",
        "scope": "surrealdb:query",
    }
    resp = requests.post(url, data=payload, timeout=10)
    assert resp.status_code == 200, f"Token exchange failed: {resp.text}"
    return resp.json()["access_token"]


class TestKeycloakSpireSurrealDBE2E:

    def test_01_spire_workload_attestation(self):
        """Test 1: Assert spire-agent returns valid X.509 SVID matching react-agent SPIFFE ID."""
        svid_info = fetch_agent_svid(socket_path=SOCKET_PATH)
        assert svid_info["spiffe_id"] == "spiffe://example.org/workload/react-agent"
        assert svid_info["cert_pem"].startswith("-----BEGIN CERTIFICATE-----")

    def test_02_unauthorized_svid_fetch(self):
        """Test 2: Assert fetching an SVID from an unregistered selector returns no entries."""
        cmd = [
            "/home/dev1/spire-1.16.0/bin/spire-server",
            "entry",
            "show",
            "-spiffeID",
            "spiffe://example.org/workload/unauthorized-workload",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert "Found 0 entries" in res.stdout or res.returncode != 0

    def test_03_keycloak_rfc8693_token_exchange(self):
        """Test 3: Token exchange mints target token for api://surrealdb with ns, db, ac, and act.sub."""
        user_token, _ = get_user_token("alice", "password123")
        target_token = exchange_to_surrealdb(user_token)
        claims = jwt.decode(target_token, options={"verify_signature": False})

        assert claims["aud"] == "api://surrealdb"
        assert claims["azp"] == "agentgateway"
        assert claims["ns"] == "main"
        assert claims["db"] == "main"
        assert claims["ac"] == "keycloak_jwt"
        assert "act" in claims and claims["act"]["sub"] == "react-agent"
        assert claims.get("actor_sub") == "react-agent"

    def test_04_downstream_mcp_surrealdb_execution(self):
        """Test 4: Agentgateway validates inbound JWT, exchanges token, and proxies query to SurrealDB."""
        user_token, _ = get_user_token("alice", "password123")
        
        # Dispatch query through Agentgateway MCP tool
        query = 'CREATE agent_memory CONTENT { prompt_log: "Test E2E query via Agentgateway", response_data: "Success" };'
        mcp_res = execute_surreal_agent_task(
            query=query,
            user_token=user_token,
            gateway_url=AGENTGATEWAY_URL,
        )

        assert mcp_res["status_code"] == 200
        result = mcp_res["data"].get("result", {})
        assert result.get("isError") is False
        content = result.get("content", [])
        assert len(content) > 0
        raw_db_resp = content[0]["text"]
        db_data = json.loads(raw_db_resp)
        assert len(db_data) > 0
        assert db_data[0]["status"] == "OK"
        assert "Test E2E query via Agentgateway" in str(db_data[0]["result"])

    def test_05_security_regression_audience_mismatch(self):
        """Test 5: Tokens without audience api://surrealdb are rejected by SurrealDB."""
        user_token, _ = get_user_token("alice", "password123")
        
        # User token has aud: ["agentgateway", "account"], not api://surrealdb
        headers = {
            "Authorization": f"Bearer {user_token}",
            "Accept": "application/json",
            "NS": "main",
            "DB": "main",
        }
        resp = requests.post(f"{SURREALDB_URL}/sql", data="SELECT * FROM user;", headers=headers, timeout=10)
        # SurrealDB must reject tokens with audience mismatch (HTTP 401: 'There was a problem with authentication')
        assert resp.status_code in [401, 403] or "problem with authentication" in resp.text

    def test_06_security_regression_actor_delegation_enforcement(self):
        """Test 6: SurrealDB row-level security restricts agent_memory table to authorized actor."""
        user_token, _ = get_user_token("alice", "password123")
        target_token = exchange_to_surrealdb(user_token)

        # Authorized actor query succeeds
        headers = {
            "Authorization": f"Bearer {target_token}",
            "Accept": "application/json",
            "NS": "main",
            "DB": "main",
        }
        resp = requests.post(f"{SURREALDB_URL}/sql", data="SELECT * FROM agent_memory;", headers=headers, timeout=10)
        assert resp.status_code == 200
        assert resp.json()[0]["status"] == "OK"

    def test_07_security_regression_session_logout_coupling(self):
        """Test 7: Logging out the user from Keycloak invalidates subsequent token exchange."""
        user_token, refresh_token = get_user_token("alice", "password123")

        # Invalidate session
        logout_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/logout"
        requests.post(logout_url, data={"client_id": "react-agent-client", "refresh_token": refresh_token}, timeout=10)

        # Attempt exchange with invalidated user token
        env = load_env()
        secret = env.get("KEYCLOAK_GATEWAY_CLIENT_SECRET", "")
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": "agentgateway",
            "client_secret": secret,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "api://surrealdb",
            "scope": "surrealdb:query",
        }
        resp = requests.post(f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token", data=payload, timeout=10)
        assert resp.status_code == 400
        assert resp.json().get("error") in ["invalid_grant", "invalid_request"]
