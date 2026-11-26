#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SPIRE_SOCKET_PATH="${SPIRE_SOCKET_PATH:-/tmp/spire-react-agent/public/api.sock}"
SPIRE_BIN="${SPIRE_BIN:-/home/dev1/spire-1.16.0/bin}"

# Check if SPIRE agent socket is active and responsive
if ! "$SPIRE_BIN/spire-agent" healthcheck -socketPath "$SPIRE_SOCKET_PATH" >/dev/null 2>&1; then
    echo "SPIRE agent not healthy on $SPIRE_SOCKET_PATH. Bootstrapping dedicated SPIRE services..."
    "$DIR/spire/scripts/setup_spire.sh"
    sleep 2
fi

echo "Authenticating react-agent workload with SPIRE NHI..."
PYTHONPATH="$DIR/src" python3 "$DIR/src/react_agent/spire_identity.py"

echo "react-agent successfully authenticated with SPIRE SVID Non-Human Identity."
