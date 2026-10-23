# NOTICE

This repository is an installer, a skill, and a patch. It does not vendor the
upstream project — `scripts/setup.py` fetches it at the pinned commit.

## Third-party code installed by this repo

**faust-machines/fusion360-mcp-server**
https://github.com/faust-machines/fusion360-mcp-server
Pinned to commit `19b9f1e9519235ae4a0f5e8dc6b029c08b87ff5f`.

```
MIT License

Copyright (c) 2025 Faust Network, Inc.
```

That project provides two components, both installed by `scripts/setup.py`:

1. `addon/` — the Fusion 360 add-in (`Fusion360MCP`), copied into Fusion's
   `API/AddIns` folder. It runs inside the user's Fusion session and listens on
   `127.0.0.1:9876`.
2. `src/fusion360_mcp/` — the MCP server, installed into a local venv and
   registered with Hermes as the `fusion360` MCP server.

Its MIT licence text is reproduced above and is also present in the cloned
upstream tree as `LICENSE`.

## Local modification applied by this repo

`scripts/setup.py` patches one function in the installed add-in
(`CommandHandler.export_step`): Fusion 2705 rejects a `BRepBody` as STEP export
geometry and raises `3 : invlid argument geometry`, so the patch passes the
owning `Component` (`body.parentComponent`) instead. The patch is idempotent and
is re-applied on every installer run, including after re-cloning upstream.

Upstream has not been asked to take this change; if you re-clone upstream by
hand instead of using the installer, STEP export will fail again.

## The CAD bridge (`bridge/`)

`bridge/` is first-party code (MIT, same as the rest of this repo). It depends on
the following, installed into `bridge/.venv` — none of it is vendored here:

| package | licence | why |
|---------|---------|-----|
| [build123d](https://github.com/gumyr/build123d) | Apache-2.0 | the CAD kernel wrapper models write against |
| [OCP](https://github.com/CadQuery/OCP) / OpenCASCADE | LGPL-2.1 (OCCT) | the geometry kernel under build123d, imported as a Python extension |
| [mcp](https://github.com/modelcontextprotocol/python-sdk) | MIT | the MCP server and client |
| [playwright](https://github.com/microsoft/playwright) | Apache-2.0 | only for `test_canvas_e2e.py`; not needed at runtime |

The knowledge corpus is hand-written, plus build123d **signatures and docstring
first paragraphs read from the installed package at index build time** — quoted
for retrieval, not redistributed as a copy. Autodesk's Fusion API documentation is
not redistributed; the Fusion chunks are short notes about observed behaviour.

## Autodesk

Fusion 360 and its API are Autodesk property, governed by the Autodesk terms of
service. This repository does not redistribute any Autodesk software. It relies
on Fusion's documented Python scripting API, which Autodesk makes available on
the free personal-use licence; Autodesk's own MCP server is a separate,
subscription-gated product and is **not** used here.

Use at your own risk. The bridge is unauthenticated on loopback by design: any
local process can drive Fusion while it is open.
