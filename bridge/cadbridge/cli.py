"""One CLI for the whole bridge.

    cadbridge search "m3 clearance counterbore"
    cadbridge stats
    cadbridge run model.py --out out
    cadbridge canvas --image photo.jpg --prompt "servo mount"
    cadbridge push out/part.step [--clear]
    cadbridge status                     # index + Fusion + canvas summary
    cadbridge serve                      # the MCP server on stdio
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="cadbridge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="query the knowledge base")
    p.add_argument("query", nargs="+")
    p.add_argument("-k", type=int, default=6)
    p.add_argument("--domain")
    p.add_argument("--full", action="store_true", help="print whole chunks")

    sub.add_parser("stats", help="index stats")

    p = sub.add_parser("run", help="execute a build123d script and verify it")
    p.add_argument("script")
    p.add_argument("--out", default="out")
    p.add_argument("--expect-volume", type=float)

    p = sub.add_parser("canvas", help="annotate an image in the browser")
    p.add_argument("--image")
    p.add_argument("--prompt", default="")
    p.add_argument("--port", type=int, default=8477)
    p.add_argument("--out", help="write annotation json here")

    p = sub.add_parser("push", help="import a STEP into the running Fusion 360")
    p.add_argument("step")
    p.add_argument("--clear", action="store_true", help="delete previous CADBridge imports")

    sub.add_parser("status", help="knowledge index, Fusion socket, canvas sessions")
    sub.add_parser("serve", help="run the MCP server on stdio")

    p = sub.add_parser("agent", help="run a local/any OpenAI-compatible model end to end")
    p.add_argument("--prompt", required=True)
    p.add_argument("--annotate")
    p.add_argument("--annotation")
    p.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    p.add_argument("--model", default="local-model")
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--push", action="store_true")

    args = ap.parse_args()

    if args.cmd == "search":
        from .rag import get_kb
        kb = get_kb()
        hits = kb.search(" ".join(args.query), k=args.k, domain=args.domain)
        if not hits:
            print("no matches")
            return 1
        for h in hits:
            print(f"\n=== [{h['id']}] {h['title']}  ({h['domain']}, score {h['score']})")
            print(h["text"] if args.full else h["text"][:400].strip() + (" ..." if len(h["text"]) > 400 else ""))
        return 0

    if args.cmd == "stats":
        from .rag import get_kb
        print(json.dumps(get_kb().stats(), indent=2))
        return 0

    if args.cmd == "run":
        from . import runner
        code = Path(args.script).read_text(encoding="utf-8")
        res = runner.run_code(code, out_dir=args.out)
        if not res.get("ok"):
            print(res["error"])
            return 1
        slim = {k: v for k, v in res.items() if k != "code"}
        print(json.dumps(slim, indent=2))
        if args.expect_volume:
            v = runner.compare(res, {"volume": args.expect_volume})
            print("VERDICT:", "PASS" if v["pass"] else "FAIL")
            for c in v["checks"]:
                print(f"  [{'ok' if c['pass'] else 'XX'}] {c['what']}: {c['detail']}")
            return 0 if v["pass"] else 2
        return 0

    if args.cmd == "canvas":
        from . import canvas
        srv = canvas.get_server(port=args.port)
        sess = srv.open_session(args.image, prompt=args.prompt)
        print(f"canvas: {srv.url(sess.id)}\nwaiting for submit ...")
        got = srv.wait(sess.id, timeout=1800)
        ann = got.get("annotation") or {}
        print(json.dumps(ann, indent=2))
        if args.out and ann:
            Path(args.out).write_text(json.dumps(ann, indent=2), encoding="utf-8")
        return 0

    if args.cmd == "push":
        from . import fusion_link
        try:
            print(json.dumps(fusion_link.push_step(args.step, clear=args.clear), indent=2))
            return 0
        except fusion_link.FusionLinkError as exc:
            print(f"error: {exc}")
            return 1

    if args.cmd == "status":
        from . import canvas, fusion_link
        from .rag import get_kb
        out = {"index": get_kb().stats(), "fusion": fusion_link.is_alive(),
               "canvas_sessions": len(canvas.get_server().sessions)}
        try:
            if out["fusion"]:
                out["fusion_document"] = fusion_link.document_info()
        except Exception as exc:
            out["fusion_error"] = str(exc)
        print(json.dumps(out, indent=2))
        return 0

    if args.cmd == "serve":
        from .server import srv
        srv.run(transport="stdio")
        return 0

    if args.cmd == "agent":
        from .agent import generate
        ann = None
        if args.annotate:
            from . import canvas
            srv = canvas.get_server()
            sess = srv.open_session(args.annotate, prompt=args.prompt)
            print(f"canvas: {srv.url(sess.id)}\nwaiting for submit ...")
            ann = (srv.wait(sess.id, timeout=1800).get("annotation") or {})
        elif args.annotation:
            ann = json.loads(Path(args.annotation).read_text(encoding="utf-8"))
        out = generate(args.base_url, args.model, None, args.prompt, ann,
                       Path("out"), attempts=args.attempts, push=args.push)
        print(json.dumps({k: v for k, v in out.items() if k != "code"}, indent=2))
        return 0 if out.get("ok") else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
