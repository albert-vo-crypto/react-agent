"""
Keycloak RFC 8693 Token Exchange Client for react-agent.
"""

import os
import requests
from typing import Dict, Any

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8082")
REALM = os.environ.get("KEYCLOAK_REALM", "myrealm")
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "react-agent")
CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "agent-secret")


def exchange_user_token(
    subject_token: str,
    audience: str = "api://agentgateway",
    scope: str = "mcp.tools.execute",
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
    keycloak_url: str = KEYCLOAK_URL,
    realm: str = REALM,
) -> Dict[str, Any]:
    """
    Call Keycloak at POST /realms/{realm}/protocol/openid-connect/token
    with grant_type=urn:ietf:params:oauth:grant-type:token-exchange.
    """
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": client_id,
        "client_secret": client_secret,
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
    }
    if audience:
        payload["audience"] = audience
    if scope:
        payload["scope"] = scope

    response = requests.post(token_url, data=payload, timeout=10)
    return {
        "status_code": response.status_code,
        "response": response.json() if response.headers.get("Content-Type", "").startswith("application/json") else response.text
    }
