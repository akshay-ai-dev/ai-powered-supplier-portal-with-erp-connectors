"""Sample MCP server for Claude Desktop: one tool that runs a little Python and returns random numbers.

Claude Desktop starts this program itself and talks to it over stdin/stdout ("stdio" transport),
which is why the config uses a `command` (uv) rather than a URL.

Run it by hand to check it starts:   uv run --with fastmcp python server.py
"""
import random

from fastmcp import FastMCP

mcp = FastMCP("Random Numbers")


@mcp.tool
def random_numbers(count: int = 10, low: int = 1, high: int = 100) -> dict:
    """Generate random whole numbers. By default: 10 numbers between 1 and 100 (inclusive)."""
    if not 1 <= count <= 1000:
        raise ValueError("count must be between 1 and 1000")
    if low > high:
        raise ValueError("low must not be greater than high")
    numbers = [random.randint(low, high) for _ in range(count)]
    return {"count": count, "range": [low, high], "numbers": numbers, "sum": sum(numbers)}


if __name__ == "__main__":
    # stdout carries the protocol, so the startup banner must stay off it
    mcp.run(transport="stdio", show_banner=False)
