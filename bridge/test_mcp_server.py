"""Talk to the MCP server exactly the way an agent would, over stdio.

    python test_mcp_server.py

Initialises a session, lists the tools, then calls a few for real: a knowledge
search, a code run with a volume verdict, and a Fusion status check.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception as exc:                                    # pragma: no cover
    print(f"cannot import the mcp client: {exc}")
    sys.exit(2)

CODE = """from build123d import *
part = Box(20, 20, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
part -= Cylinder(2, 7, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -1)))
"""
# 20*20*5 - pi*4*5 = 2000 - 62.83 = 1937.17


def text_of(result) -> str:
    """First text block of a CallToolResult."""
    for block in result.content:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            return block.text
    raise RuntimeError(f"no text content in {result}")


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "cadbridge.server"],
                                   cwd=str(HERE))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            si = getattr(init, "server_info", None) or getattr(init, "serverInfo")
            print(f"connected: {si.name} v{si.version}")

            tools = (await session.list_tools()).tools
            names = sorted(t.name for t in tools)
            print(f"{len(names)} tools: {names}")

            search = await session.call_tool("cad_knowledge_search",
                                             {"query": "servo mount bracket sg90", "k": 3})
            hits = json.loads(text_of(search))
            print("\nsearch:", [h["id"] for h in hits["results"]])
            assert hits["count"] >= 1, "knowledge search returned nothing"
            assert any(h["id"] in ("rec-005", "hw-003") for h in hits["results"]), \
                f"expected a servo chunk, got {[h['id'] for h in hits['results']]}"

            run = await session.call_tool("cad_run_code", {
                "code": CODE, "expect_volume": 1937.17,
                "out_dir": str(HERE / "out_mcp_test")})
            res = json.loads(text_of(run))
            print("\nrun:", {k: res.get(k) for k in
                             ("ok", "volume_mm3", "bbox_mm", "solids", "valid")})
            print("verdict:", res.get("verdict", {}).get("checks"))
            assert res["ok"] and abs(res["volume_mm3"] - 1937.17) < 2, "volume mismatch"
            assert res["solids"] == 1 and res["valid"]

            ctx = await session.call_tool("cad_context", {"query": "servo mount", "k": 3})
            block = json.loads(text_of(ctx))
            assert "House rules" in block["context"], "briefing missing house rules"
            print(f"\nbriefing: {len(block['context'])} chars, chunks={block['chunks']}")

            st = await session.call_tool("fusion_status", {})
            print("\nfusion:", json.loads(text_of(st)))

    print("\nPASS — MCP server answers over stdio")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
