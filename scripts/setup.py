#!/usr/bin/env python3
"""Fusion2Hermes setup - bridges Autodesk Fusion 360 to Hermes over MCP.

One command. Idempotent: re-running repairs and upgrades in place.

    python scripts/setup.py          # install / repair
    python scripts/setup.py --check  # verify only, change nothing

What it does
  1. Finds the installed Fusion build.
  2. Fetches the MIT-licensed Fusion360MCP add-in (pinned commit; falls back to
     a tarball download when git is missing) and copies it into Fusion's
     AddIns folder with runOnStartup enabled.
  3. Patches the add-in's STEP exporter (Fusion 2705 rejects a BRepBody as STEP
     geometry; a Component works).
  4. Creates a venv for the MCP server and installs it.
  5. Ensures Hermes has the MCP SDK (`hermes pm install --extra mcp`).
  6. Registers the server as `fusion360` in Hermes.
  7. Copies the skill, its scripts, and its references into the Hermes skills
     directory.

Licence note: this installer is MIT (see LICENSE). The add-in and the MCP
server it installs are MIT, copyright Faust Network, Inc. - see NOTICE.md.
Nothing here is uploaded anywhere; the socket is 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import venv
from pathlib import Path

REPO = "https://github.com/faust-machines/fusion360-mcp-server"
PIN = "19b9f1e9519235ae4a0f5e8dc6b029c08b87ff5f"
TARBALL = f"https://codeload.github.com/faust-machines/fusion360-mcp-server/tar.gz/{PIN}"
ADDIN_DIRNAME = "Fusion360MCP"
MCP_NAME = "fusion360"
PORT = 9876
ROOT = Path(__file__).resolve().parent.parent
SKILL_SRC_NAME = "fusion2hermes"

OK, BAD, INFO = "[ok]", "[!!]", "[..]"


def say(mark: str, msg: str) -> None:
    print(f"{mark} {msg}", flush=True)


def run(cmd: list[str], *, cwd: Path | None = None, stdin: str | None = None,
        timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        input=stdin, timeout=timeout,
    )


def which(name: str) -> str | None:
    return shutil.which(name)


# --------------------------------------------------------------------------- #
# environment discovery
# --------------------------------------------------------------------------- #
def fusion_addins_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise SystemExit("APPDATA is not set - cannot locate Fusion's AddIns folder")
        return Path(appdata) / "Autodesk" / "Autodesk Fusion 360" / "API" / "AddIns"
    home = Path.home()
    return (home / "Library" / "Application Support" / "Autodesk"
            / "Autodesk Fusion 360" / "API" / "AddIns")


def fusion_builds() -> list[tuple[tuple[int, int, int], Path]]:
    """Installed Fusion builds, newest first, as (version, dir)."""
    if sys.platform == "win32":
        roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk" / "webdeploy" / "production"]
    else:
        roots = [Path.home() / "Library" / "Application Support" / "Autodesk"
                 / "webdeploy" / "production"]
    found: list[tuple[tuple[int, int, int], Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            vj = d / "version.json"
            if not vj.is_file():
                continue
            try:
                v = json.loads(vj.read_text(encoding="utf-8"))
                key = (int(v.get("major", 0)), int(v.get("minor", 0)), int(v.get("build", 0)))
            except Exception:
                key = (0, 0, 0)
            found.append((key, d))
    return sorted(found, key=lambda t: t[0], reverse=True)


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"
        if (cand / "skills").is_dir() or cand.is_dir():
            return cand
    return Path.home() / ".hermes"


def state_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Fusion2Hermes"
    else:
        base = Path.home() / ".cache" / "Fusion2Hermes"
    base.mkdir(parents=True, exist_ok=True)
    return base


def port_open(port: int = PORT, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 1. upstream fetch
# --------------------------------------------------------------------------- #
def fetch_upstream() -> Path:
    """Return a directory containing addon/ at the pinned commit."""
    cache = state_dir() / "upstream"
    if (cache / "addon" / "Fusion360MCP.py").is_file():
        say(OK, f"upstream add-in already cached at {cache}")
        return cache

    git = which("git")
    if git:
        say(INFO, f"cloning {REPO} @ {PIN[:8]}")
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
        cp = run([git, "clone", "--quiet", REPO, str(cache)], timeout=600)
        if cp.returncode != 0:
            say(BAD, f"git clone failed: {cp.stderr.strip()[:300]}")
        else:
            cp = run([git, "checkout", "--quiet", PIN], cwd=cache, timeout=120)
            if cp.returncode != 0:
                say(BAD, f"checkout {PIN[:8]} failed: {cp.stderr.strip()[:300]}")
            if (cache / "addon" / "Fusion360MCP.py").is_file():
                say(OK, f"cloned to {cache}")
                return cache

    say(INFO, "downloading tarball instead of using git")
    tmp = state_dir() / "upstream.tar.gz"
    urllib.request.urlretrieve(TARBALL, tmp)
    with tarfile.open(tmp) as tf:
        members = tf.getmembers()
        root = members[0].name.split("/")[0]
        tf.extractall(state_dir())
    extracted = state_dir() / root
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    extracted.rename(cache)
    tmp.unlink(missing_ok=True)
    if not (cache / "addon" / "Fusion360MCP.py").is_file():
        raise SystemExit("upstream download did not produce addon/Fusion360MCP.py")
    say(OK, f"extracted to {cache}")
    return cache


# --------------------------------------------------------------------------- #
# 2. install add-in + patch
# --------------------------------------------------------------------------- #
def install_addin(upstream: Path) -> Path:
    target = fusion_addins_dir() / ADDIN_DIRNAME
    addins = target.parent
    if not addins.is_dir():
        say(INFO, f"creating {addins}")
        addins.mkdir(parents=True, exist_ok=True)

    if target.exists():
        backup = target.with_name(f"{ADDIN_DIRNAME}.bak")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        shutil.move(str(target), str(backup))
        say(INFO, f"previous install backed up to {backup.name}")
    shutil.copytree(upstream / "addon", target)
    say(OK, f"add-in installed at {target}")

    # runOnStartup so the user never opens Tools > Scripts and Add-Ins
    manifest = target / "Fusion360MCP.manifest"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        data["runOnStartup"] = True
        manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        say(OK, "manifest: runOnStartup = true")
    except Exception as exc:
        say(BAD, f"could not set runOnStartup in manifest: {exc}")
    return target


OLD_STEP_A = """        if occ is None:
            step_opts = export_mgr.createSTEPExportOptions(file_path, body)
            export_mgr.execute(step_opts)
            return {"exported": True, "body": body_name, "file_path": file_path}"""

NEW_STEP_A = """        # Fusion 2705 refuses a BRepBody as STEP geometry ("invlid argument
        # geometry"); a Component is accepted. Export the body's owning
        # component, falling back to the whole design if that is refused too.
        # (Fusion2Hermes patch - see NOTICE.md)
        if occ is None:
            geometry = body.parentComponent
            try:
                step_opts = export_mgr.createSTEPExportOptions(file_path, geometry)
            except Exception:
                step_opts = export_mgr.createSTEPExportOptions(file_path)
            export_mgr.execute(step_opts)
            return {"exported": True, "body": body_name, "file_path": file_path}"""

OLD_STEP_B = """            step_opts = export_mgr.createSTEPExportOptions(file_path, occ)
            export_mgr.execute(step_opts)"""

NEW_STEP_B = """            comp = occ.component if occ is not None else body.parentComponent
            try:
                step_opts = export_mgr.createSTEPExportOptions(file_path, comp)
            except Exception:
                step_opts = export_mgr.createSTEPExportOptions(file_path)
            export_mgr.execute(step_opts)"""


def patch_step_export(*paths: Path) -> None:
    for path in paths:
        if not path.is_file():
            say(BAD, f"patch target missing: {path}")
            continue
        raw = path.read_text(encoding="utf-8", newline="")
        nl = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        if "geometry = body.parentComponent" in text:
            say(OK, f"STEP patch already applied: {path.name}")
            continue
        if OLD_STEP_A not in text or OLD_STEP_B not in text:
            say(BAD, f"patch anchored text not found in {path} - upstream changed? "
                     "STEP export may need a manual fix.")
            continue
        text = text.replace(OLD_STEP_A, NEW_STEP_A, 1).replace(OLD_STEP_B, NEW_STEP_B, 1)
        path.write_text(text.replace("\n", nl), encoding="utf-8", newline="")
        say(OK, f"STEP export patched: {path}")


# --------------------------------------------------------------------------- #
# 3. MCP server venv
# --------------------------------------------------------------------------- #
def ensure_server_venv(upstream: Path) -> Path:
    venv_dir = upstream / ".venv"
    py = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if py.is_file():
        say(OK, f"MCP server venv exists: {venv_dir}")
        return py

    uv = which("uv")
    host_py = sys.executable
    if uv:
        say(INFO, "creating venv with uv")
        cp = run([uv, "venv", "--python", "3.13", str(venv_dir)], timeout=600)
        if cp.returncode != 0:
            cp = run([uv, "venv", "--python", "3.12", str(venv_dir)], timeout=600)
        if cp.returncode != 0:
            say(BAD, f"uv venv failed: {cp.stderr.strip()[:400]}")
            uv = None
    if not uv:
        say(INFO, f"creating venv with {host_py}")
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))

    if not py.is_file():
        raise SystemExit(f"venv python not found at {py}")

    say(INFO, "installing the MCP server (this pulls the `mcp` SDK)")
    if uv:
        cp = run([uv, "pip", "install", "--python", str(py), "-e", "."], cwd=upstream, timeout=900)
    else:
        cp = run([str(py), "-m", "pip", "install", "--quiet", "-e", "."], cwd=upstream, timeout=900)
    if cp.returncode != 0:
        raise SystemExit(f"installing the MCP server failed:\n{cp.stdout[-1500:]}\n{cp.stderr[-1500:]}")
    say(OK, "MCP server installed")
    return py


# --------------------------------------------------------------------------- #
# 4. Hermes registration
# --------------------------------------------------------------------------- #
def hermes(*args: str, stdin: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    exe = which("hermes")
    if not exe:
        raise SystemExit("`hermes` is not on PATH - run this from a shell where `hermes` works")
    return run([exe, *args], stdin=stdin, timeout=timeout)


def register_mcp(py: Path) -> bool:
    ls = hermes("mcp", "ls", timeout=180)
    if MCP_NAME in (ls.stdout or ""):
        say(INFO, f"'{MCP_NAME}' already registered - removing before re-adding")
        hermes("mcp", "remove", MCP_NAME, stdin="y\n", timeout=180)

    say(INFO, "registering the MCP server in Hermes")
    cp = hermes("mcp", "add", MCP_NAME, "--command", str(py),
                "--args", "-m", "fusion360_mcp", stdin="y\n", timeout=600)
    out = f"{cp.stdout or ''}{cp.stderr or ''}"

    if "requires the 'mcp' Python SDK" in out:
        say(INFO, "Hermes is missing the MCP SDK - installing it (hermes pm install --extra mcp)")
        pm = hermes("pm", "install", "--extra", "mcp", timeout=1800)
        if pm.returncode != 0:
            say(BAD, "hermes pm install --extra mcp failed:\n" + (pm.stdout or "")[-1200:])
            return False
        cp = hermes("mcp", "add", MCP_NAME, "--command", str(py),
                    "--args", "-m", "fusion360_mcp", stdin="y\n", timeout=600)
        out = f"{cp.stdout or ''}{cp.stderr or ''}"

    if "Saved '" in out or "Saved \"" in out:
        tools = re.search(r"\((\d+)/(\d+) tools enabled\)", out)
        detail = f" ({tools.group(1)} tools)" if tools else ""
        say(OK, f"registered '{MCP_NAME}' in Hermes{detail}")
        return True
    say(BAD, "registration did not report success:\n" + out[-1200:])
    return False


# --------------------------------------------------------------------------- #
# 5. skill install
# --------------------------------------------------------------------------- #
def install_skill() -> Path:
    dest = hermes_home() / "skills" / "creative" / SKILL_SRC_NAME
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "SKILL.md", dest / "SKILL.md")
    (dest / "scripts").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "scripts" / "fm_client.py", dest / "scripts" / "fm_client.py")
    if (ROOT / "references").is_dir():
        shutil.copytree(ROOT / "references", dest / "references", dirs_exist_ok=True)
    (dest / "VERSION").write_text(PIN + "\n", encoding="utf-8")
    say(OK, f"skill installed at {dest}")
    return dest


# --------------------------------------------------------------------------- #
# 6. verification
# --------------------------------------------------------------------------- #
def verify(py: Path) -> int:
    failures = 0
    target = fusion_addins_dir() / ADDIN_DIRNAME
    if (target / "Fusion360MCP.py").is_file():
        say(OK, "add-in present")
    else:
        say(BAD, f"add-in missing at {target}")
        failures += 1

    ls = hermes("mcp", "ls", timeout=180)
    if MCP_NAME in (ls.stdout or ""):
        say(OK, f"'{MCP_NAME}' registered in Hermes")
    else:
        say(BAD, f"'{MCP_NAME}' not registered - run: hermes mcp add {MCP_NAME} ...")
        failures += 1

    if not port_open():
        say(INFO, "Fusion's add-in socket is closed - start (or restart) Fusion, "
                  "then re-run this check")
        failures += 1
    else:
        say(OK, f"add-in socket listening on 127.0.0.1:{PORT}")
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from fm_client import send  # type: ignore
            r = send("get_scene_info", timeout=30)
            if r.get("status") == "success":
                say(OK, "live handshake OK - Fusion is ready for modelling")
            else:
                say(BAD, f"handshake returned {r}")
                failures += 1
        except Exception as exc:
            say(BAD, f"socket open but handshake failed: {exc}")
            failures += 1
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Connect Fusion 360 to Hermes over MCP")
    ap.add_argument("--check", action="store_true", help="verify only, change nothing")
    ap.add_argument("--skip-skill", action="store_true", help="do not copy the skill")
    args = ap.parse_args(argv)

    print("Fusion2Hermes - bridging Fusion 360 to Hermes\n")

    builds = fusion_builds()
    if builds:
        ver, path = builds[0]
        say(OK, f"Fusion {ver[0]}.{ver[1]}.{ver[2]} at {path}")
    else:
        say(BAD, "no Fusion build found - install Fusion (desktop) and sign in once first")

    if args.check:
        py = state_dir() / "upstream" / ".venv" / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        return verify(py)

    if not builds:
        return 1

    upstream = fetch_upstream()
    target = install_addin(upstream)
    patch_step_export(upstream / "addon" / "server" / "command_handler.py",
                      target / "server" / "command_handler.py")
    py = ensure_server_venv(upstream)
    ok = register_mcp(py)
    if not args.skip_skill:
        install_skill()

    print()
    if port_open():
        say(OK, "add-in socket already live")
    else:
        say(INFO, "next: start (or restart) Fusion 360. The add-in self-starts on launch.")
        say(INFO, "then run:  python scripts/setup.py --check")
    say(INFO, "in Hermes: run /reload-mcp (or start a new session) to load the "
              "mcp_fusion360_* tools")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
