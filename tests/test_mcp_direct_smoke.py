"""Direct (no-LLM) MCP tool-call check: confirms the tigergraph-mcp wiring itself works, independent of any
agent loop. Requires a live Savanna workspace. Run: .venv/bin/python tests/test_mcp_direct_smoke.py"""

import asyncio, json, sys
sys.path.insert(0, ".")
from agent.tools.graph_mcp import graph_mcp_tools

async def main():
    async with graph_mcp_tools() as tools:
        by = {t.name: t for t in tools}
        r1 = await by["tigergraph__run_installed_query"].ainvoke({
            "query_name": "card_neighbourhood", "graph_name": "FraudGraph",
            "params": {"card": "C03528-K1", "asof": "2016-09-01 00:00:00", "days": 60}})
        print("card_neighbourhood result:", str(r1)[:500])
        r2 = await by["tigergraph__run_installed_query"].ainvoke({
            "query_name": "trace_chain", "graph_name": "FraudGraph",
            "params": {"txn": 3514030, "n_prev": 2, "n_next": 2}})
        print("trace_chain result:", str(r2)[:600])

asyncio.run(main())
