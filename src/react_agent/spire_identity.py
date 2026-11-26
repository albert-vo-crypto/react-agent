"""
SPIFFE / SPIRE Identity Provider for react-agent.

Interacts with the SPIRE Agent Workload API over a Unix Domain Socket to retrieve
cryptographic X.509 and JWT SVIDs for Non-Human Identity (NHI) authentication.
"""

import os
import subprocess
import logging
from typing import Dict, Any

logger = logging.getLogger("react_agent.spire_identity")

SPIRE_SOCKET_PATH = os.environ.get(
    "SPIRE_SOCKET_PATH",
    "/tmp/spire-react-agent/public/api.sock"
    if os.path.exists("/tmp/spire-react-agent/public/api.sock")
    else "/tmp/spire-agent/public/api.sock"
)
SPIRE_BIN = os.environ.get("SPIRE_BIN", "/home/dev1/spire-1.16.0/bin")


def check_spire_agent_socket() -> bool:
    """Check if the SPIRE Agent Workload API Unix Domain Socket is available."""
    exists = os.path.exists(SPIRE_SOCKET_PATH)
    if not exists:
        logger.warning(f"SPIRE agent socket not found at {SPIRE_SOCKET_PATH}")
    return exists


def fetch_workload_svid(output_dir: str = "/tmp") -> Dict[str, Any]:
    """
    Fetch an X.509-SVID from the SPIRE Agent Workload API.
    
    Returns a dict containing:
      - spiffe_id: The SPIFFE URI assigned to this workload
      - cert_path: Path to the issued leaf certificate
      - key_path: Path to the associated private key
      - bundle_path: Path to the root CA bundle
    """
    if not check_spire_agent_socket():
        raise RuntimeError(
            f"Cannot fetch SVID: SPIRE Workload API socket not found at {SPIRE_SOCKET_PATH}. "
            "Ensure SPIRE Agent is running."
        )

    fetch_cmd = [
        os.path.join(SPIRE_BIN, "spire-agent"),
        "api",
        "fetch",
        "x509",
        "-socketPath",
        SPIRE_SOCKET_PATH,
        "-write",
        output_dir,
    ]

    res = subprocess.run(fetch_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"SPIRE Workload API fetch failed: {res.stderr.strip()}")

    cert_path = os.path.join(output_dir, "svid.0.pem")
    key_path = os.path.join(output_dir, "svid.0.key")
    bundle_path = os.path.join(output_dir, "bundle.0.pem")

    # Extract SPIFFE ID (URI SAN) from certificate using openssl
    openssl_cmd = ["openssl", "x509", "-in", cert_path, "-text", "-noout"]
    cert_text = subprocess.run(openssl_cmd, capture_output=True, text=True, check=True).stdout

    spiffe_id = None
    for line in cert_text.splitlines():
        if "URI:spiffe://" in line:
            spiffe_id = line.strip().replace("URI:", "")
            break

    return {
        "spiffe_id": spiffe_id,
        "cert_path": cert_path,
        "key_path": key_path,
        "bundle_path": bundle_path,
        "raw_output": res.stdout,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        identity = fetch_workload_svid()
        print("=" * 60)
        print("🔐 SPIRE NON-HUMAN IDENTITY (NHI) ATTESTED")
        print("=" * 60)
        print(f"SPIFFE ID:     {identity['spiffe_id']}")
        print(f"Cert Path:     {identity['cert_path']}")
        print(f"Key Path:      {identity['key_path']}")
        print(f"CA Bundle:     {identity['bundle_path']}")
        print("=" * 60)
    except Exception as exc:
        print(f"❌ Failed to fetch SPIRE SVID: {exc}")
        exit(1)
