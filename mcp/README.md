# TigerGraph MCP

We use the official server, `pip install tigergraph-mcp` (https://github.com/tigergraph/tigergraph-mcp),
installed into `.venv`. A reference clone lives at `mcp/tigergraph-mcp/` for docs/examples (git-ignored;
`git clone https://github.com/tigergraph/tigergraph-mcp.git mcp/tigergraph-mcp` to restore it).

## Config
`mcp/.env` (git-ignored, mirrors `../.env`): `TG_HOST` (with `https://` scheme), `TG_GRAPHNAME=FraudGraph`,
`TG_SECRET`, `TG_TGCLOUD=true`. Auth is secret-based (pyTigerGraph mints/refreshes a token itself); see
`NOTES.md` Phase 3 for the Savanna wake-latency note that also applies to this path.

## Launch
`mcp/launch.sh` starts the server over stdio, the mode our LangGraph agent uses (each tool call subprocess
is spawned and owned by the client, per the server's own README). Not meant to be run by hand except to
smoke-test that it starts.

## What the agent uses
`agent/tools/graph_mcp.py` opens one stdio session per agent run (not one per call, per the server's "Reusing
one server process" guidance) and loads all `tigergraph__*` tools via `langchain-mcp-adapters`. The agent binds
a subset (`run_installed_query`, `gsql`, `get_neighbors`, the vector-search tools) to the LLM; see `agent/`.
