#!/usr/bin/env bash
# Launch the TigerGraph MCP server against our Savanna workspace (stdio transport, for a single agent process).
# Usage: mcp/launch.sh [-v|-vv]
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/tigergraph-mcp --env-file mcp/.env "$@"
