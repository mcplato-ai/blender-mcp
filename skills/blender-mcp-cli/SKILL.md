---
name: blender-mcp-cli
description: Prepare, verify, and operate Blender through the direct blender-mcp-cli TCP/JSON client without MCP. Use when Codex needs to install or configure the Blender add-on, validate the localhost socket, discover CLI capabilities, inspect or modify Blender scenes, run bpy scripts, capture viewport images, or use Poly Haven, Sketchfab, Hyper3D, or Hunyuan3D from an automation or LLM workflow.
---

# Blender MCP CLI

Control the unchanged Blender MCP add-on through its direct CLI. Treat the
add-on endpoint as raw TCP/JSON on `localhost:9876`, not HTTP or MCP.

## Prepare The Environment

1. Use Blender 3.0 or newer with its GUI. Do not use `blender -b`; the add-on
   dispatches work through Blender's main event loop.
2. Obtain `addon.py` from the `mcplato-ai/blender-mcp` repository or its release
   assets. Install and enable it in Blender through
   `Edit > Preferences > Add-ons`.
3. Confirm the BlenderMCP sidebar reports that its socket server is running on
   port `9876`. The current add-on normally starts it automatically. Keep a
   useful `VIEW_3D` area visible when screenshots are required.
4. Install the CLI:

```bash
python -m pip install --upgrade blender-mcp-cli
```

For a source checkout, use `python -m pip install -e .` from the repository root.

5. Verify installation and connectivity:

```bash
blender-mcp-cli --version
blender-mcp-cli --pretty schema
blender-mcp-cli --pretty status all
```

The defaults are a 10-second connection timeout and a 180-second response
timeout. Override them with global `--connect-timeout` and `--timeout` options.

Enable and configure optional integrations in the BlenderMCP sidebar before
using their commands. API credentials live on the Blender side.

## Follow The Operating Workflow

1. Run `blender-mcp-cli schema` or the relevant `--help` before composing a
   command. Put global options such as `--host`, `--port`, and `--pretty` before
   the command group.
2. Inspect before changing anything:

```bash
blender-mcp-cli --pretty scene info
blender-mcp-cli viewport screenshot /absolute/path/before.png
```

3. Prefer first-class subcommands. Use `raw call` only for an add-on command or
   parameter not represented by the current CLI.
4. Put multiline Blender Python in a file or stdin instead of shell-escaped
   inline text:

```bash
blender-mcp-cli code exec --file /absolute/path/change_scene.py

blender-mcp-cli code exec --stdin <<'PY'
import bpy
print(bpy.context.scene.name)
PY
```

Only send trusted code. `code exec` is unsandboxed and can access everything the
Blender process can access. Print values that must be returned to the caller.

5. Inspect the scene and capture another screenshot after mutations. Correct
   failures before reporting completion.

## Interpret Results

- Parse stdout as one JSON object when the exit code is `0`.
- Parse stderr as one JSON error object when the exit code is non-zero.
- Treat exit `3` as connection failure, `4` as timeout, `5` as protocol failure,
  `6` as an outer Blender error, `7` as an operation failure, and `8` as local
  file I/O failure.
- Never retry a timed-out mutation automatically. Blender may still complete it.
- After a timeout, wait for Blender to respond and use read-only `scene info`,
  screenshots, or an idempotent inspection script to reconcile the result.

## Handle Paths And Remote Access

- Use absolute paths for screenshots, scripts, and local assets.
- Screenshot paths are interpreted by Blender and must be visible to both
  processes.
- The unchanged add-on binds to localhost and has no authentication or TLS.
  For remote Blender, use a controlled SSH tunnel and point `--host`/`--port`
  at the forwarded socket. Do not expose the port publicly.
- If a connection fails, verify Blender is open in GUI mode, the add-on is
  enabled, and the configured port matches before changing code.
