#!/usr/bin/env python3
"""Raw TCP client for the Fusion360MCP add-in (localhost:9876).

The add-in speaks newline-delimited JSON: {"type": "<cmd>", "params": {...}}
and answers {"status": "success"|"error", "result": {...}}.

This is the low-level path - it works immediately, with no Hermes restart.
Once `hermes mcp` has the fusion360 stdio server registered, the same
operations are available as mcp_fusion360_* tools instead.

Usage:
  python fm_client.py <command> ['<json params>']
  python fm_client.py --list          # every command the add-in exposes
"""
import json
import socket
import sys

HOST, PORT = "127.0.0.1", 9876


def send(cmd, params=None, timeout=120.0):
    with socket.create_connection((HOST, PORT), timeout=10) as s:
        s.settimeout(timeout)
        s.sendall((json.dumps({"type": cmd, "params": params or {}}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.split(b"\n", 1)[0])


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "--list":
        r = send("list_commands")
        print(json.dumps(r, indent=2)[:8000])
        return 0
    cmd = argv[1]
    params = json.loads(argv[2]) if len(argv) > 2 else {}
    r = send(cmd, params)
    print(json.dumps(r, indent=2)[:20000])
    return 0 if r.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
