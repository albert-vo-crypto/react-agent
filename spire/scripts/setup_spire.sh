#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SPIRE_BIN="${SPIRE_BIN:-/home/dev1/spire-1.16.0/bin}"

# Clean previous transient data
rm -rf /tmp/spire-react-data /tmp/spire-react-server /tmp/spire-react-agent
mkdir -p /tmp/spire-react-data/server /tmp/spire-react-data/agent /tmp/spire-react-server/private /tmp/spire-react-agent/public

echo "=== Starting SPIRE Server (port 18081) ==="
cd "$DIR"
setsid "$SPIRE_BIN/spire-server" run -config spire/conf/server/server.conf > /tmp/spire_react_server.log 2>&1 < /dev/null &
sleep 2

"$SPIRE_BIN/spire-server" healthcheck -socketPath /tmp/spire-react-server/private/api.sock
echo "SPIRE Server is healthy."

echo "=== Pre-registering react-agent Non-Human Identity (NHI) ==="
"$SPIRE_BIN/spire-server" entry create \
    -socketPath /tmp/spire-react-server/private/api.sock \
    -parentID spiffe://example.org/agent-node \
    -spiffeID spiffe://example.org/workload/react-agent \
    -selector unix:uid:$(id -u) \
    -x509SVIDTTL 3600

echo "Generating join token for node attestation..."
TOKEN_OUTPUT=$("$SPIRE_BIN/spire-server" token generate \
    -socketPath /tmp/spire-react-server/private/api.sock \
    -spiffeID spiffe://example.org/agent-node)
JOIN_TOKEN=$(echo "$TOKEN_OUTPUT" | awk '{print $2}')
echo "Join Token generated: $JOIN_TOKEN"

echo "=== Starting SPIRE Agent ==="
setsid "$SPIRE_BIN/spire-agent" run -config spire/conf/agent/agent.conf -joinToken "$JOIN_TOKEN" > /tmp/spire_react_agent.log 2>&1 < /dev/null &
sleep 3

"$SPIRE_BIN/spire-agent" healthcheck -socketPath /tmp/spire-react-agent/public/api.sock
echo "SPIRE Agent is healthy."

echo "Workload entry registered successfully."
echo "Workload API Socket: /tmp/spire-react-agent/public/api.sock"
