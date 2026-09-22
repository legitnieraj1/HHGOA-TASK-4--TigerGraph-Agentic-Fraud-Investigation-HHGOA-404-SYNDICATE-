"""Phase 3 integration check (spec: "a smoke test where the LLM tool-calls the MCP to fetch one customer's
neighbourhood and a money trace"). Requires a live Savanna workspace + GEMINI_API_KEY. Not a unit test --
run manually: .venv/bin/python tests/test_mcp_agent_smoke.py"""

"""Phase 3 check: an LLM tool-calls the TigerGraph MCP server to fetch a customer's neighbourhood and a money trace."""
import asyncio
import json
import os
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from agent.tools.graph_mcp import graph_mcp_tools


async def main():
    async with graph_mcp_tools() as tools:
        wanted = {"tigergraph__run_installed_query"}
        bound = [t for t in tools if t.name in wanted]
        print("bound:", [t.name for t in bound])

        llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", google_api_key=os.environ["GEMINI_API_KEY"], temperature=0)
        agent = create_react_agent(llm, bound)

        prompt = (
            "Tool `run_installed_query` takes {query_name, graph_name, params}. Two calls, in order:\n"
            '1. run_installed_query(query_name="card_neighbourhood", graph_name="FraudGraph", '
            'params={"card": "C03528-K1", "asof": "2016-09-01 00:00:00", "days": 60})\n'
            '2. run_installed_query(query_name="trace_chain", graph_name="FraudGraph", '
            'params={"txn": 3514030, "n_prev": 2, "n_next": 2})\n'
            "Make exactly these two tool calls, then report: how many other cards shared a device with C03528-K1 "
            "(from call 1's own_devices/other_cards_by_device), and the txn ids in trace_chain's previous/next lists."
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]}, config={"recursion_limit": 8})
        for m in result["messages"]:
            role = getattr(m, "type", "?")
            if role == "ai" and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    print(f"[TOOL CALL] {tc['name']}({json.dumps(tc['args'])[:200]})")
            elif role == "tool":
                print(f"[TOOL RESULT] {m.name}: {str(m.content)[:200]}")
            elif role == "ai" and m.content:
                print(f"[AI] {str(m.content)[:800]}")

asyncio.run(main())
