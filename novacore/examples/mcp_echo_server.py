from mcp.server.fastmcp import FastMCP


server = FastMCP(
    "NovaCore MCP Demo"
)


@server.tool()
def echo(
    text: str,
) -> str:
    """Return the provided text unchanged."""
    return text


if __name__ == "__main__":
    server.run(
        transport="stdio",
    )