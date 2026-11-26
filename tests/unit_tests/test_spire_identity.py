"""
Tests for SPIFFE/SPIRE Workload Attestation and SVID retrieval in react-agent.
"""

import os
import subprocess
import pytest
from react_agent.spire_identity import check_spire_agent_socket, fetch_workload_svid, SPIRE_SOCKET_PATH


@pytest.fixture(scope="session", autouse=True)
def ensure_spire_running():
    """Ensure dedicated SPIRE services are running for test session."""
    spire_bin = os.environ.get("SPIRE_BIN", "/home/dev1/spire-1.16.0/bin")
    socket_path = os.environ.get("SPIRE_SOCKET_PATH", "/tmp/spire-react-agent/public/api.sock")
    
    check_cmd = [os.path.join(spire_bin, "spire-agent"), "healthcheck", "-socketPath", socket_path]
    res = subprocess.run(check_cmd, capture_output=True)
    if res.returncode != 0:
        setup_script = os.path.join(os.path.dirname(__file__), "../../spire/scripts/setup_spire.sh")
        subprocess.run(["bash", setup_script], check=True)


def test_spire_agent_socket_availability():
    """Verify that the SPIRE Agent Workload API socket is present."""
    assert check_spire_agent_socket(), f"SPIRE agent socket must exist at {SPIRE_SOCKET_PATH}"


def test_fetch_workload_svid():
    """Verify fetching X.509-SVID NHI and validate expected SPIFFE ID."""
    identity = fetch_workload_svid(output_dir="/tmp")
    assert identity["spiffe_id"] == "spiffe://example.org/workload/react-agent"
    assert os.path.exists(identity["cert_path"])
    assert os.path.exists(identity["key_path"])
    assert os.path.exists(identity["bundle_path"])
