"""Command-line client for the unmodified Blender MCP add-on."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from . import __version__
from .connection import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RESPONSE_TIMEOUT,
    BlenderClient,
    BlenderClientError,
)


EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_OPERATION = 7
EXIT_LOCAL_IO = 8


class CLIError(Exception):
    kind = "cli_error"
    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


class CLIUsageError(CLIError):
    kind = "usage_error"
    exit_code = EXIT_USAGE


class BlenderOperationError(CLIError):
    kind = "operation_error"
    exit_code = EXIT_OPERATION


class LocalIOError(CLIError):
    kind = "local_io_error"
    exit_code = EXIT_LOCAL_IO


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _number(value: str) -> int | float:
    try:
        if not any(character in value.lower() for character in (".", "e")):
            return int(value)
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from exc


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _parser(
    *,
    prog: str | None = None,
    description: str | None = None,
    epilog: str | None = None,
) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _add_subcommands(parser: argparse.ArgumentParser, title: str = "commands"):
    return parser.add_subparsers(dest="subcommand", title=title, required=True)


def _set_simple_command(
    parser: argparse.ArgumentParser,
    command_type: str,
    *parameter_map: tuple[str, str],
    constants: dict[str, Any] | None = None,
) -> None:
    parser.set_defaults(
        handler=_handle_simple,
        command_type=command_type,
        parameter_map=parameter_map,
        command_constants=constants or {},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _parser(
        prog="blender-mcp-cli",
        description="""Control Blender through the existing Blender MCP add-on socket.

This CLI talks directly to the add-on's raw TCP/JSON port. It does not use MCP
and does not require any change to addon.py. Start Blender with its GUI and make
sure the BlenderMCP add-on server is running before issuing commands.

Successful commands write one JSON object to stdout. Errors write one JSON
object to stderr and return a non-zero exit code.""",
        epilog="""Examples:
  blender-mcp-cli --pretty status all
  blender-mcp-cli --pretty scene info
  blender-mcp-cli --pretty object info Cube
  blender-mcp-cli code exec --file create_scene.py
  blender-mcp-cli viewport screenshot ./viewport.png --max-size 1000
  blender-mcp-cli raw call get_scene_info
  blender-mcp-cli --pretty schema

Environment:
  BLENDER_HOST                 Blender socket host (default: localhost)
  BLENDER_PORT                 Blender socket port (default: 9876)
  BLENDER_CONNECT_TIMEOUT      Connection timeout in seconds (default: 10)
  BLENDER_TIMEOUT              Response timeout in seconds (default: 180)

Exit codes:
  0 success, 2 usage, 3 connection, 4 timeout, 5 protocol,
  6 Blender command error, 7 operation error, 8 local file error""",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("BLENDER_HOST", DEFAULT_HOST),
        help="Blender socket host (env: BLENDER_HOST; default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("BLENDER_PORT", DEFAULT_PORT),
        help="Blender socket port (env: BLENDER_PORT; default: %(default)s)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=_positive_float,
        default=_env_float("BLENDER_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        help="connection timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=_env_float("BLENDER_TIMEOUT", DEFAULT_RESPONSE_TIMEOUT),
        help="response timeout in seconds; timed-out commands are not retried (default: %(default)s)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent JSON output for humans (default output is compact)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    commands = _add_subcommands(parser)
    _build_schema_command(commands)
    _build_status_commands(commands)
    _build_scene_commands(commands)
    _build_object_commands(commands)
    _build_viewport_commands(commands)
    _build_code_commands(commands)
    _build_polyhaven_commands(commands)
    _build_sketchfab_commands(commands)
    _build_hyper3d_commands(commands)
    _build_hunyuan3d_commands(commands)
    _build_raw_commands(commands)
    return parser


def _build_schema_command(commands) -> None:
    parser = commands.add_parser(
        "schema",
        help="print machine-readable CLI capability information",
        description="Print the direct Blender command catalog for LLM discovery.",
    )
    parser.set_defaults(handler=_handle_schema, command_type="schema", local_only=True)


def _build_status_commands(commands) -> None:
    parser = commands.add_parser(
        "status",
        help="check the Blender connection and optional integrations",
        description="Check one integration or all Blender add-on capabilities.",
    )
    subcommands = _add_subcommands(parser, "status targets")
    status_commands = {
        "telemetry": "get_telemetry_consent",
        "polyhaven": "get_polyhaven_status",
        "hyper3d": "get_hyper3d_status",
        "sketchfab": "get_sketchfab_status",
        "hunyuan3d": "get_hunyuan3d_status",
    }
    for name, command_type in status_commands.items():
        child = subcommands.add_parser(name, help=f"check {name} status")
        _set_simple_command(child, command_type)
    all_parser = subcommands.add_parser(
        "all", help="check the connection and all optional integrations"
    )
    all_parser.set_defaults(handler=_handle_status_all, command_type="status_all")


def _build_scene_commands(commands) -> None:
    parser = commands.add_parser("scene", help="inspect the current Blender scene")
    subcommands = _add_subcommands(parser)
    info = subcommands.add_parser(
        "info", help="return a summary of the current scene and up to 10 objects"
    )
    _set_simple_command(info, "get_scene_info")


def _build_object_commands(commands) -> None:
    parser = commands.add_parser("object", help="inspect Blender objects")
    subcommands = _add_subcommands(parser)
    info = subcommands.add_parser(
        "info", help="return transform, material, mesh, and bounding-box information"
    )
    info.add_argument("name", help="exact Blender object name")
    _set_simple_command(info, "get_object_info", ("name", "name"))


def _build_viewport_commands(commands) -> None:
    parser = commands.add_parser("viewport", help="capture the Blender 3D viewport")
    subcommands = _add_subcommands(parser)
    screenshot = subcommands.add_parser(
        "screenshot",
        help="save a PNG screenshot through Blender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Capture the active VIEW_3D area as a PNG.

The output path is interpreted by the Blender process. With remote tunnels it
must refer to a filesystem location visible to both Blender and this CLI.""",
    )
    screenshot.add_argument("output", help="PNG output path visible to Blender")
    screenshot.add_argument(
        "--max-size",
        type=_positive_int,
        default=1000,
        help="maximum width or height in pixels (default: %(default)s)",
    )
    screenshot.set_defaults(
        handler=_handle_screenshot, command_type="get_viewport_screenshot"
    )


def _build_code_commands(commands) -> None:
    parser = commands.add_parser(
        "code",
        help="execute Python inside Blender",
        description="Execute arbitrary Python with bpy available inside Blender.",
    )
    subcommands = _add_subcommands(parser)
    execute = subcommands.add_parser(
        "exec",
        help="run Python code in Blender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Run arbitrary Python in Blender. This is not sandboxed.

Use --file or stdin for multiline code. Only printed stdout is returned; call
print(...) when the caller needs a value.""",
        epilog="""Examples:
  blender-mcp-cli code exec --code "print(bpy.context.scene.name)"
  blender-mcp-cli code exec --file script.py
  printf 'print(bpy.app.version_string)' | blender-mcp-cli code exec --stdin""",
    )
    source = execute.add_mutually_exclusive_group()
    source.add_argument("--code", help="Python source code")
    source.add_argument("--file", help="UTF-8 Python file, or - for stdin")
    source.add_argument(
        "--stdin", action="store_true", help="read Python source from stdin"
    )
    execute.set_defaults(handler=_handle_code, command_type="execute_code")


def _build_polyhaven_commands(commands) -> None:
    parser = commands.add_parser(
        "polyhaven",
        help="search, download, and apply Poly Haven assets",
        description="Requires 'Use assets from Poly Haven' in the BlenderMCP panel.",
    )
    subcommands = _add_subcommands(parser)

    categories = subcommands.add_parser("categories", help="list asset categories")
    categories.add_argument(
        "--type",
        dest="asset_type",
        choices=("hdris", "textures", "models", "all"),
        default="hdris",
        help="asset type (default: %(default)s)",
    )
    _set_simple_command(
        categories, "get_polyhaven_categories", ("asset_type", "asset_type")
    )

    search = subcommands.add_parser("search", help="search Poly Haven assets")
    search.add_argument(
        "--type",
        dest="asset_type",
        choices=("all", "hdris", "textures", "models"),
        default="all",
        help="asset type (default: %(default)s)",
    )
    search.add_argument(
        "--categories", help="comma-separated Poly Haven category names"
    )
    _set_simple_command(
        search,
        "search_polyhaven_assets",
        ("asset_type", "asset_type"),
        ("categories", "categories"),
    )

    download = subcommands.add_parser(
        "download", help="download and import an HDRI, texture, or model"
    )
    download.add_argument("asset_id", help="Poly Haven asset ID")
    download.add_argument(
        "--type",
        dest="asset_type",
        choices=("hdris", "textures", "models"),
        required=True,
        help="asset type",
    )
    download.add_argument(
        "--resolution", default="1k", help="asset resolution (default: %(default)s)"
    )
    download.add_argument(
        "--format", dest="file_format", help="preferred file format"
    )
    _set_simple_command(
        download,
        "download_polyhaven_asset",
        ("asset_id", "asset_id"),
        ("asset_type", "asset_type"),
        ("resolution", "resolution"),
        ("file_format", "file_format"),
    )

    texture = subcommands.add_parser(
        "set-texture", help="apply a previously downloaded texture to an object"
    )
    texture.add_argument("object_name", help="target Blender object name")
    texture.add_argument("texture_id", help="downloaded Poly Haven texture ID")
    _set_simple_command(
        texture,
        "set_texture",
        ("object_name", "object_name"),
        ("texture_id", "texture_id"),
    )


def _build_sketchfab_commands(commands) -> None:
    parser = commands.add_parser(
        "sketchfab",
        help="search, preview, and download Sketchfab models",
        description="Requires Sketchfab to be enabled and configured in Blender.",
    )
    subcommands = _add_subcommands(parser)

    search = subcommands.add_parser("search", help="search downloadable models")
    search.add_argument("query", help="model search query")
    search.add_argument("--categories", help="comma-separated category names")
    search.add_argument(
        "--count",
        type=_positive_int,
        default=20,
        help="maximum result count (default: %(default)s)",
    )
    downloadable = search.add_mutually_exclusive_group()
    downloadable.add_argument(
        "--downloadable",
        dest="downloadable",
        action="store_true",
        default=True,
        help="return only downloadable models (default)",
    )
    downloadable.add_argument(
        "--include-nondownloadable",
        dest="downloadable",
        action="store_false",
        help="include models that cannot be downloaded",
    )
    _set_simple_command(
        search,
        "search_sketchfab_models",
        ("query", "query"),
        ("categories", "categories"),
        ("count", "count"),
        ("downloadable", "downloadable"),
    )

    preview = subcommands.add_parser(
        "preview", help="download a model preview image to a local file"
    )
    preview.add_argument("uid", help="Sketchfab model UID")
    preview.add_argument("--output", required=True, help="local image output path")
    preview.set_defaults(
        handler=_handle_sketchfab_preview,
        command_type="get_sketchfab_model_preview",
    )

    download = subcommands.add_parser(
        "download", help="download, import, and normalize a model"
    )
    download.add_argument("uid", help="Sketchfab model UID")
    download.add_argument(
        "--target-size",
        type=_positive_float,
        required=True,
        help="largest imported dimension in Blender units/meters",
    )
    _set_simple_command(
        download,
        "download_sketchfab_model",
        ("uid", "uid"),
        ("target_size", "target_size"),
        constants={"normalize_size": True},
    )


def _add_bbox_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bbox",
        nargs=3,
        type=_number,
        metavar=("LENGTH", "WIDTH", "HEIGHT"),
        help="positive proportions; non-integer values are normalized to max=100",
    )


def _build_hyper3d_commands(commands) -> None:
    parser = commands.add_parser(
        "hyper3d",
        help="generate and import models with Hyper3D Rodin",
        description="Requires Hyper3D to be enabled and configured in Blender.",
    )
    subcommands = _add_subcommands(parser)

    text = subcommands.add_parser("generate-text", help="create a text-to-3D job")
    text.add_argument("text", help="English model description")
    _add_bbox_argument(text)
    text.set_defaults(handler=_handle_hyper3d_text, command_type="create_rodin_job")

    images = subcommands.add_parser(
        "generate-images",
        help="create an image-to-3D job",
        description="""Create a Rodin image-to-3D job.

Use --image with hyper3d.ai MAIN_SITE mode. Use --image-url with fal.ai mode.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = images.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--image",
        action="append",
        dest="images",
        metavar="PATH",
        help="local image path; repeat for multiple views",
    )
    source.add_argument(
        "--image-url",
        action="append",
        dest="image_urls",
        metavar="URL",
        help="remote image URL; repeat for multiple views",
    )
    _add_bbox_argument(images)
    images.set_defaults(
        handler=_handle_hyper3d_images, command_type="create_rodin_job"
    )

    poll = subcommands.add_parser("poll", help="poll a Rodin generation job")
    identifier = poll.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--subscription-key", help="hyper3d.ai subscription key")
    identifier.add_argument("--request-id", help="fal.ai request ID")
    _set_simple_command(
        poll,
        "poll_rodin_job_status",
        ("subscription_key", "subscription_key"),
        ("request_id", "request_id"),
    )

    import_asset = subcommands.add_parser(
        "import", help="download and import a completed Rodin model"
    )
    import_asset.add_argument("name", help="Blender object/mesh name")
    identifier = import_asset.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--task-uuid", help="hyper3d.ai task UUID")
    identifier.add_argument("--request-id", help="fal.ai request ID")
    _set_simple_command(
        import_asset,
        "import_generated_asset",
        ("name", "name"),
        ("task_uuid", "task_uuid"),
        ("request_id", "request_id"),
    )


def _build_hunyuan3d_commands(commands) -> None:
    parser = commands.add_parser(
        "hunyuan3d",
        help="generate and import models with Hunyuan3D",
        description="Requires Hunyuan3D to be enabled and configured in Blender.",
    )
    subcommands = _add_subcommands(parser)

    generate = subcommands.add_parser(
        "generate",
        help="submit a Hunyuan3D generation request",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Provide text, an image path/URL, or both.

Official API mode accepts exactly one source. Local API mode may accept both.
Local image paths are opened by Blender and must be visible on its machine.""",
    )
    generate.add_argument("--text", help="English or Chinese model description")
    generate.add_argument("--image", help="image path visible to Blender, or HTTP URL")
    generate.set_defaults(
        handler=_handle_hunyuan_generate, command_type="create_hunyuan_job"
    )

    poll = subcommands.add_parser("poll", help="poll an official Hunyuan3D job")
    poll.add_argument("job_id", help="job ID, with or without the job_ prefix")
    _set_simple_command(
        poll, "poll_hunyuan_job_status", ("job_id", "job_id")
    )

    import_asset = subcommands.add_parser(
        "import", help="download and import an official Hunyuan3D OBJ ZIP"
    )
    import_asset.add_argument("name", help="Blender object name")
    import_asset.add_argument("zip_url", help="HTTP(S) URL returned by Hunyuan3D")
    _set_simple_command(
        import_asset,
        "import_generated_asset_hunyuan",
        ("name", "name"),
        ("zip_url", "zip_file_url"),
    )


def _build_raw_commands(commands) -> None:
    parser = commands.add_parser(
        "raw",
        help="send any current or future add-on command",
        description="Low-level access to the add-on's {type, params} protocol.",
    )
    subcommands = _add_subcommands(parser)
    call = subcommands.add_parser(
        "call",
        help="send one raw command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  blender-mcp-cli raw call get_scene_info
  blender-mcp-cli raw call get_object_info --params '{"name":"Cube"}'
  blender-mcp-cli raw call execute_code --params-file request.json""",
    )
    call.add_argument("type", help="add-on command type")
    params = call.add_mutually_exclusive_group()
    params.add_argument("--params", help="JSON object containing command parameters")
    params.add_argument(
        "--params-file", help="UTF-8 file containing a JSON object, or - for stdin"
    )
    call.set_defaults(handler=_handle_raw, command_type="raw_call")


def _client_from_args(args: argparse.Namespace) -> BlenderClient:
    if not 1 <= args.port <= 65535:
        raise CLIUsageError("--port must be between 1 and 65535")
    return BlenderClient(
        host=args.host,
        port=args.port,
        connect_timeout=args.connect_timeout,
        response_timeout=args.timeout,
    )


def _handle_simple(args: argparse.Namespace, client: BlenderClient) -> Any:
    params = dict(args.command_constants)
    for attribute, wire_name in args.parameter_map:
        value = getattr(args, attribute)
        if value is not None:
            params[wire_name] = value
    return _execute(client, args.command_type, params)


def _handle_status_all(args: argparse.Namespace, client: BlenderClient) -> Any:
    commands = {
        "telemetry": "get_telemetry_consent",
        "polyhaven": "get_polyhaven_status",
        "hyper3d": "get_hyper3d_status",
        "sketchfab": "get_sketchfab_status",
        "hunyuan3d": "get_hunyuan3d_status",
    }
    return {name: _execute(client, command_type, {}) for name, command_type in commands.items()}


def _handle_screenshot(args: argparse.Namespace, client: BlenderClient) -> Any:
    output = _output_path(args.output)
    result = _execute(
        client,
        "get_viewport_screenshot",
        {"max_size": args.max_size, "filepath": str(output), "format": "png"},
    )
    if not output.exists():
        raise BlenderOperationError(
            "Blender reported screenshot success, but the output file is not visible to the CLI",
            details={
                "output": str(output),
                "hint": "Use a path visible to the Blender process and the CLI.",
                "result": result,
            },
        )
    enriched = dict(result) if isinstance(result, dict) else {"blender_result": result}
    enriched["output"] = str(output)
    enriched["bytes"] = output.stat().st_size
    return enriched


def _handle_code(args: argparse.Namespace, client: BlenderClient) -> Any:
    if args.code is not None:
        code = args.code
    elif args.file is not None:
        code = _read_text(args.file, label="Python source")
    elif args.stdin or not sys.stdin.isatty():
        code = sys.stdin.read()
    else:
        raise CLIUsageError("provide --code, --file, --stdin, or pipe Python on stdin")
    if not code.strip():
        raise CLIUsageError("Python source is empty")
    return _execute(client, "execute_code", {"code": code})


def _handle_sketchfab_preview(args: argparse.Namespace, client: BlenderClient) -> Any:
    output = _output_path(args.output)
    result = _execute(client, "get_sketchfab_model_preview", {"uid": args.uid})
    if not isinstance(result, dict) or not result.get("image_data"):
        raise BlenderOperationError(
            "Sketchfab preview response did not contain image_data", details=result
        )
    try:
        image_bytes = base64.b64decode(result["image_data"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BlenderOperationError(
            "Sketchfab preview returned invalid base64 image data", details=result
        ) from exc
    try:
        output.write_bytes(image_bytes)
    except OSError as exc:
        raise LocalIOError(f"Could not write preview image {output}: {exc}") from exc
    metadata = {key: value for key, value in result.items() if key != "image_data"}
    metadata["output"] = str(output)
    metadata["bytes"] = len(image_bytes)
    return metadata


def _handle_hyper3d_text(args: argparse.Namespace, client: BlenderClient) -> Any:
    return _execute(
        client,
        "create_rodin_job",
        {
            "text_prompt": args.text,
            "images": None,
            "bbox_condition": _process_bbox(args.bbox),
        },
    )


def _handle_hyper3d_images(args: argparse.Namespace, client: BlenderClient) -> Any:
    if args.images:
        images: list[Any] = []
        for value in args.images:
            path = Path(value).expanduser()
            if not path.is_file():
                raise LocalIOError(f"Image file does not exist: {path}")
            try:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError as exc:
                raise LocalIOError(f"Could not read image {path}: {exc}") from exc
            images.append((path.suffix, encoded))
    else:
        images = list(args.image_urls)
        invalid = [url for url in images if not _is_http_url(url)]
        if invalid:
            raise CLIUsageError(
                "--image-url values must use http:// or https://",
                details={"invalid_urls": invalid},
            )
    return _execute(
        client,
        "create_rodin_job",
        {
            "text_prompt": None,
            "images": images,
            "bbox_condition": _process_bbox(args.bbox),
        },
    )


def _handle_hunyuan_generate(args: argparse.Namespace, client: BlenderClient) -> Any:
    if not args.text and not args.image:
        raise CLIUsageError("provide --text, --image, or both")
    return _execute(
        client,
        "create_hunyuan_job",
        {"text_prompt": args.text, "image": args.image},
    )


def _handle_raw(args: argparse.Namespace, client: BlenderClient) -> Any:
    if args.params is not None:
        params = _parse_json_object(args.params, "--params")
    elif args.params_file is not None:
        params = _parse_json_object(
            _read_text(args.params_file, label="JSON parameters"), "--params-file"
        )
    else:
        params = {}
    args.command_type = args.type
    return _execute(client, args.type, params)


def _handle_schema(args: argparse.Namespace, client: BlenderClient | None) -> Any:
    return COMMAND_SCHEMA


def _execute(client: BlenderClient, command_type: str, params: dict[str, Any]) -> Any:
    result = client.call(command_type, params)
    _raise_for_operation_failure(result)
    return result


def _raise_for_operation_failure(result: Any) -> None:
    if isinstance(result, dict):
        if result.get("error"):
            raise BlenderOperationError(str(result["error"]), details=result)
        response = result.get("Response")
        if isinstance(response, dict) and response.get("Error"):
            nested_error = response["Error"]
            message = (
                nested_error.get("Message", str(nested_error))
                if isinstance(nested_error, dict)
                else str(nested_error)
            )
            raise BlenderOperationError(message, details=result)
        for flag in ("success", "succeed"):
            if result.get(flag) is False:
                message = result.get("message") or result.get("error") or f"{flag}=false"
                raise BlenderOperationError(str(message), details=result)
    elif isinstance(result, str) and result.lstrip().lower().startswith("error:"):
        raise BlenderOperationError(result, details=result)


def _output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.parent.is_dir():
        raise LocalIOError(f"Output directory does not exist: {path.parent}")
    return path


def _read_text(value: str, *, label: str) -> str:
    if value == "-":
        return sys.stdin.read()
    path = Path(value).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LocalIOError(f"Could not read {label} file {path}: {exc}") from exc
    except UnicodeError as exc:
        raise LocalIOError(f"{label} file is not valid UTF-8: {path}") from exc


def _parse_json_object(value: str, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CLIUsageError(f"{source} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CLIUsageError(f"{source} must contain a JSON object")
    return parsed


def _process_bbox(values: list[int | float] | None) -> list[int] | None:
    if values is None:
        return None
    if any(value <= 0 for value in values):
        raise CLIUsageError("--bbox values must be greater than zero")
    if all(isinstance(value, int) for value in values):
        return [int(value) for value in values]
    maximum = max(float(value) for value in values)
    return [int(float(value) / maximum * 100) for value in values]


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _emit(payload: dict[str, Any], *, pretty: bool, stream) -> None:
    json.dump(
        payload,
        stream,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    stream.write("\n")
    stream.flush()


def _error_payload(error: Exception) -> dict[str, Any]:
    kind = getattr(error, "kind", "internal_error")
    details = getattr(error, "details", None)
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"kind": kind, "message": str(error)},
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        client = None if getattr(args, "local_only", False) else _client_from_args(args)
        result = args.handler(args, client)
        _emit(
            {"ok": True, "command": args.command_type, "result": result},
            pretty=args.pretty,
            stream=sys.stdout,
        )
        return 0
    except KeyboardInterrupt:
        _emit(
            _error_payload(CLIError("Interrupted by user")),
            pretty=args.pretty,
            stream=sys.stderr,
        )
        return 130
    except (BlenderClientError, CLIError) as exc:
        _emit(_error_payload(exc), pretty=args.pretty, stream=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        _emit(
            _error_payload(CLIError(f"Unexpected error: {exc}")),
            pretty=args.pretty,
            stream=sys.stderr,
        )
        return EXIT_INTERNAL


COMMAND_SCHEMA = {
    "transport": {
        "kind": "raw TCP with one JSON request and one JSON response",
        "default_host": DEFAULT_HOST,
        "default_port": DEFAULT_PORT,
        "request": {"type": "COMMAND_TYPE", "params": {}},
        "response": {
            "success": {"status": "success", "result": "ANY_JSON_VALUE"},
            "error": {"status": "error", "message": "STRING"},
        },
        "notes": [
            "This is not HTTP and does not use MCP.",
            "Commands are never retried automatically after a timeout.",
            "Use raw call for add-on commands not represented by a first-class subcommand.",
        ],
    },
    "commands": [
        {"cli": "status telemetry", "type": "get_telemetry_consent", "params": {}},
        {"cli": "status polyhaven", "type": "get_polyhaven_status", "params": {}},
        {"cli": "status hyper3d", "type": "get_hyper3d_status", "params": {}},
        {"cli": "status sketchfab", "type": "get_sketchfab_status", "params": {}},
        {"cli": "status hunyuan3d", "type": "get_hunyuan3d_status", "params": {}},
        {"cli": "scene info", "type": "get_scene_info", "params": {}},
        {"cli": "object info NAME", "type": "get_object_info", "params": {"name": "string"}},
        {"cli": "viewport screenshot OUTPUT", "type": "get_viewport_screenshot", "params": {"max_size": "positive integer", "filepath": "string", "format": "png"}},
        {"cli": "code exec", "type": "execute_code", "params": {"code": "string"}},
        {"cli": "polyhaven categories", "type": "get_polyhaven_categories", "params": {"asset_type": "hdris|textures|models|all"}},
        {"cli": "polyhaven search", "type": "search_polyhaven_assets", "params": {"asset_type": "all|hdris|textures|models", "categories": "optional CSV string"}},
        {"cli": "polyhaven download ASSET_ID", "type": "download_polyhaven_asset", "params": {"asset_id": "string", "asset_type": "hdris|textures|models", "resolution": "string", "file_format": "optional string"}},
        {"cli": "polyhaven set-texture OBJECT TEXTURE_ID", "type": "set_texture", "params": {"object_name": "string", "texture_id": "string"}},
        {"cli": "sketchfab search QUERY", "type": "search_sketchfab_models", "params": {"query": "string", "categories": "optional CSV string", "count": "positive integer", "downloadable": "boolean"}},
        {"cli": "sketchfab preview UID --output PATH", "type": "get_sketchfab_model_preview", "params": {"uid": "string"}},
        {"cli": "sketchfab download UID --target-size N", "type": "download_sketchfab_model", "params": {"uid": "string", "normalize_size": True, "target_size": "positive number"}},
        {"cli": "hyper3d generate-text TEXT", "type": "create_rodin_job", "params": {"text_prompt": "string", "images": None, "bbox_condition": "optional [L,W,H]"}},
        {"cli": "hyper3d generate-images", "type": "create_rodin_job", "params": {"text_prompt": None, "images": "local base64 tuples or URL list", "bbox_condition": "optional [L,W,H]"}},
        {"cli": "hyper3d poll", "type": "poll_rodin_job_status", "params": {"subscription_key": "hyper3d.ai key", "request_id": "fal.ai ID"}},
        {"cli": "hyper3d import NAME", "type": "import_generated_asset", "params": {"name": "string", "task_uuid": "hyper3d.ai UUID", "request_id": "fal.ai ID"}},
        {"cli": "hunyuan3d generate", "type": "create_hunyuan_job", "params": {"text_prompt": "optional string", "image": "optional Blender-visible path or URL"}},
        {"cli": "hunyuan3d poll JOB_ID", "type": "poll_hunyuan_job_status", "params": {"job_id": "string"}},
        {"cli": "hunyuan3d import NAME ZIP_URL", "type": "import_generated_asset_hunyuan", "params": {"name": "string", "zip_file_url": "HTTP(S) URL"}},
        {"cli": "raw call TYPE", "type": "ANY_ADDON_COMMAND", "params": "any JSON object"},
    ],
    "exit_codes": {
        "0": "success",
        "2": "usage error",
        "3": "connection error",
        "4": "timeout; command execution state may be unknown",
        "5": "socket protocol error",
        "6": "Blender returned status=error",
        "7": "Blender handler returned an operation failure",
        "8": "local file read/write error",
    },
}


if __name__ == "__main__":
    raise SystemExit(main())
