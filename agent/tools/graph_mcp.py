"""One stdio session to tigergraph-mcp, reused across calls (per the server's own guidance -- a fresh session per
call would spawn a subprocess each time). Exposes the tools as LangChain BaseTool objects via langchain-mcp-adapters.

Usage:
    async with graph_mcp_tools() as tools:
        tool_by_name = {t.name: t for t in tools}
        ...
"""
import contextlib
import pathlib

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "mcp" / "launch.sh"


@contextlib.asynccontextmanager
async def graph_mcp_tools():
    params = StdioServerParameters(command=str(LAUNCH), args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            yield tools
