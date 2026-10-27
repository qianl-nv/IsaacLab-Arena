# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Execute the asset generator through a local Blender MCP server (host Python with mcp installed)."""

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="mcp-for-blender")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--output", type=Path, default=Path("artifacts/jetson_thor_packing/assets"))
    parser.add_argument("--prompt-file", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    code = f"OUTPUT = {str(output)!r}\n" + Path(__file__).with_name("build_assets.py").read_text()
    params = StdioServerParameters(command=args.server, args=["--port", str(args.port)])
    with (output / "mcp_server.log").open("w") as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(minutes=10)) as session:
                await session.initialize()
                result = await session.call_tool(
                    "execute_blender_code", {"code": code, "user_prompt": args.prompt_file.read_text().strip()}
                )
                (output / "mcp_result.json").write_text(result.model_dump_json(indent=2))
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                assert not result.isError, "Blender MCP reported an error"
                assert (output / "dimensions.json").is_file(), "Blender did not finish exporting the assets"


if __name__ == "__main__":
    asyncio.run(main())
