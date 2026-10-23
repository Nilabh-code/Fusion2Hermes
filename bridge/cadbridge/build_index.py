"""Build the knowledge index used by cad_knowledge_search.

Sources, in order:
  1. curated.py          — hand-written rules, tables, recipes (the important part)
  2. the installed build123d package — every public symbol + its docstring, so the
     model can look up a real signature instead of hallucinating one
  3. this repo's references/tools.md and references/troubleshooting.md — the Fusion
     MCP surface and its known failure modes

    python -m cadbridge.build_index                 # BM25 only (no deps)
    python -m cadbridge.build_index --dense         # + embeddings (needs fastembed)
    python -m cadbridge.build_index --stats
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent          # bridge/cadbridge -> bridge -> repo root
CORPUS = HERE / "corpus"
OUT = CORPUS / "index.json"

MAX_DOC = 1400


def _chunk(cid, domain, kind, title, text, tags, source="") -> dict:
    text = text.strip()
    if len(text) > MAX_DOC:
        text = text[:MAX_DOC].rstrip() + " ..."
    return dict(id=cid, domain=domain, kind=kind, title=title, text=text,
                tags=tags, source=source)


def from_curated() -> list[dict]:
    sys.path.insert(0, str(HERE.parent))
    from cadbridge.corpus.curated import CHUNKS  # type: ignore

    out = []
    for c in CHUNKS:
        out.append(_chunk(c["id"], c["domain"], c.get("kind", "doc"), c["title"],
                          c["text"], c.get("tags", []), c.get("source", "curated")))
    return out


def from_build123d() -> list[dict]:
    """One chunk per public symbol: real signature + real docstring."""
    try:
        import build123d as bd
    except Exception as exc:                                   # pragma: no cover
        print(f"  [skip] build123d not importable ({exc})")
        return []
    names = sorted(n for n in dir(bd) if not n.startswith("_"))
    out = []
    for n in names:
        obj = getattr(bd, n)
        mod = getattr(obj, "__module__", "") or ""
        if not mod.startswith("build123d"):
            continue
        doc = inspect.getdoc(obj) or ""
        if not doc:
            continue
        try:
            sig = str(inspect.signature(obj))
        except Exception:
            sig = ""
        if sig in ("(*args, **kwargs)", "(*values)"):
            try:
                sig = str(inspect.signature(obj.__init__)).replace("self, ", "").replace("(self)", "()")
            except Exception:
                pass
        head = doc.split("\n\n")[0].strip()[:400]
        body = doc[:MAX_DOC]
        text = f"`{n}{sig}`\n\n{body}"
        tags = [n.lower(), mod.replace("build123d.", "")]
        out.append(_chunk(f"api-{n.lower()}", "build123d_api", "api",
                          f"{n}(): {head.splitlines()[0][:90]}", text, tags,
                          source=f"build123d {getattr(bd, '__version__', '')}"))
    return out


def _md_sections(path: Path, prefix: str, domain: str) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"\n(?=#{2,3} )", raw)
    out = []
    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) < 60:
            continue
        title = part.splitlines()[0].lstrip("# ").strip()[:90]
        out.append(_chunk(f"{prefix}-{i:03d}", domain, "doc", title, part,
                          [w.lower() for w in re.findall(r"[A-Za-z_]{4,}", title)][:8],
                          source=path.name))
    return out


def from_repo() -> list[dict]:
    out = []
    out += _md_sections(REPO / "references" / "tools.md", "ftool", "fusion_tools")
    out += _md_sections(REPO / "references" / "troubleshooting.md", "ftrouble", "fusion_tools")
    out += _md_sections(REPO / "SKILL.md", "skill", "workflow")
    return out


def build_dense(chunks: list[dict], model_name: str) -> bool:
    try:
        from fastembed import TextEmbedding
    except Exception:
        print("  [skip] fastembed not installed (pip install fastembed) — BM25 only")
        return False
    try:
        import numpy as np
    except Exception:
        print("  [skip] numpy missing")
        return False
    texts = [f"{c['title']}\n{c['text']}" for c in chunks]
    emb = TextEmbedding(model_name=model_name)
    vecs = np.asarray(list(emb.embed(texts)), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / np.where(norms == 0, 1, norms)
    np.save(OUT.with_suffix(".vecs.npy"), vecs)
    print(f"  [ok] dense vectors {vecs.shape} -> {OUT.with_suffix('.vecs.npy').name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true", help="also build embeddings")
    ap.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--stats", action="store_true", help="print stats for existing index")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    if args.stats:
        p = Path(args.out)
        if not p.exists():
            print(f"no index at {p}")
            return 1
        raw = json.loads(p.read_text(encoding="utf-8"))
        from collections import Counter
        doms = Counter(c["domain"] for c in raw["chunks"])
        kinds = Counter(c["kind"] for c in raw["chunks"])
        print(json.dumps({"chunks": len(raw["chunks"]), "domains": dict(doms),
                          "kinds": dict(kinds), "dense_model": raw.get("dense_model"),
                          "built_at": raw.get("built_at"), "path": str(p)}, indent=2))
        return 0

    t0 = time.time()
    print("building knowledge index")
    chunks: list[dict] = []
    for name, fn in (("curated", from_curated), ("build123d api", from_build123d),
                     ("repo docs", from_repo)):
        got = fn()
        print(f"  {name}: {len(got)}")
        chunks += got

    seen: dict[str, int] = {}
    uniq = []
    for c in chunks:
        if c["id"] in seen:
            seen[c["id"]] += 1
            c = dict(c, id=f"{c['id']}-{seen[c['id']]}")
        else:
            seen[c["id"]] = 0
        uniq.append(c)
    chunks = uniq

    dense_ok = build_dense(chunks, args.model) if args.dense else False
    payload = {
        "version": 2,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dense_model": args.model if dense_ok else None,
        "chunks": chunks,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(json.dumps({
        "chunks": len(chunks),
        "domains": dict(Counter(c["domain"] for c in chunks)),
        "kinds": dict(Counter(c["kind"] for c in chunks)),
        "bytes": out.stat().st_size, "dense": dense_ok,
        "seconds": round(time.time() - t0, 2), "out": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
