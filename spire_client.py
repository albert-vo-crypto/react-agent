"""
SPIRE Client for react-agent.
Interacts with the SPIRE Agent Workload API over a Unix Domain Socket to fetch SVID credentials.
"""

import os
import subprocess
from typing import Dict, Any

SPIRE_SOCKET_PATH = os.environ.get("SPIRE_SOCKET_PATH", "/tmp/spire-agent/public/api.sock")
SPIRE_BIN = os.environ.get("SPIRE_BIN", "/home/dev1/spire-1.16.0/bin")


def check_spire_socket() -> bool:
    """Check if SPIRE Workload API socket exists."""
    return os.path.exists(SPIRE_SOCKET_PATH)


def fetch_agent_svid(output_dir: str = "/tmp", socket_path: str = SPIRE_SOCKET_PATH) -> Dict[str, Any]:
    """
    Connect to /tmp/spire-agent/public/api.sock and retrieve the agent's
    X.509-SVID client certificate (URI:spiffe://example.org/workload/react-agent) and key.
    """
    if not os.path.exists(socket_path):
        raise RuntimeError(f"SPIRE Workload API socket not found at {socket_path}")

    fetch_cmd = [
        os.path.join(SPIRE_BIN, "spire-agent"),
        "api",
        "fetch",
        "x509",
        "-socketPath",
        socket_path,
        "-write",
        output_dir,
    ]

    res = subprocess.run(fetch_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"SPIRE Workload API fetch failed: {res.stderr.strip()}")

    cert_path = os.path.join(output_dir, "svid.0.pem")
    key_path = os.path.join(output_dir, "svid.0.key")
    bundle_path = os.path.join(output_dir, "bundle.0.pem")

    # Extract SPIFFE ID (URI SAN)
    openssl_cmd = ["openssl", "x509", "-in", cert_path, "-text", "-noout"]
    cert_text = subprocess.run(openssl_cmd, capture_output=True, text=True, check=True).stdout

    spiffe_id = None
    for line in cert_text.splitlines():
        if "URI:spiffe://" in line:
            spiffe_id = line.strip().replace("URI:", "")
            break

    with open(cert_path, "r") as f:
        cert_pem = f.read()
    with open(key_path, "r") as f:
        key_pem = f.read()

    return {
        "spiffe_id": spiffe_id,
        "cert_path": cert_path,
        "key_path": key_path,
        "bundle_path": bundle_path,
        "cert_pem": cert_pem,
        "key_pem": key_pem,
    }


if __name__ == "__main__":
    svid_data = fetch_agent_svid()
    print(f"Attested SPIFFE ID: {svid_data['spiffe_id']}")
