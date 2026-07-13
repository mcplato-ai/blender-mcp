"""Blender automation through MCP or the direct TCP CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("blender-mcp-cli")
except PackageNotFoundError:
    # Package is not installed (e.g. running from a source checkout)
    __version__ = "unknown"

__all__ = [
    "__version__",
    "BlenderClient",
    "BlenderConnection",
    "get_blender_connection",
]


def __getattr__(name):
    """Keep legacy exports without importing FastMCP for direct CLI users."""
    if name == "BlenderClient":
        from .connection import BlenderClient

        return BlenderClient
    if name in {"BlenderConnection", "get_blender_connection"}:
        from .server import BlenderConnection, get_blender_connection

        return {
            "BlenderConnection": BlenderConnection,
            "get_blender_connection": get_blender_connection,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
