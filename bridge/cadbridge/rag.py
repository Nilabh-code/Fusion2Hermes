"""Retrieval for the CAD bridge: BM25 over a curated corpus, dense + rerank when available.

Pure stdlib for the core path (BM25 + RRF), so the bridge works on a bare Python
install. If `fastembed` (or `sentence-transformers`) happens to be importable the
index also carries vectors and scoring becomes hybrid; if a cross-encoder is
available it reranks the top-N. No hard dependencies, no network at query time.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

STOP = set("""a an and are as at be but by can for from has have how i if in into is it its
of on or so that the their then there these this to use used using was what when where which
who will with you your do does not no than then them they we our than""".split())

TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text).lower()
    toks = []
    for t in TOKEN_RE.findall(text):
        if t in STOP or len(t) < 2:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        toks.append(t)
    return toks


@dataclass
class Chunk:
    id: str
    domain: str
    title: str
    text: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    kind: str = "doc"          # doc | api | recipe | rule

    @property
    def tokens(self) -> list[str]:
        extra = " ".join(self.tags)
        return tokenize(f"{self.title} {self.title} {extra} {self.text}")

    def to_dict(self) -> dict[str, Any]:
        d = dict(id=self.id, domain=self.domain, title=self.title, text=self.text,
                 tags=self.tags, source=self.source, kind=self.kind)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Chunk":
        return Chunk(**d)


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(1, self.N)
        self.df: Counter = Counter()
        for d in docs:
            for t in set(d):
                self.df[t] += 1
        self.tf = [Counter(d) for d in docs]
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in self.df.items()}

    def scores(self, query: list[str]) -> list[float]:
        q = [t for t in query if t in self.idf]
        out = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i]) or 1
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if not f:
                    continue
                s += self.idf[t] * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


def _rrf(rank_lists: Iterable[list[int]], k: int = 60, n: int = 0) -> list[tuple[int, float]]:
    acc: dict[int, float] = {}
    for ranks in rank_lists:
        for pos, idx in enumerate(ranks):
            acc[idx] = acc.get(idx, 0.0) + 1.0 / (k + pos + 1)
    out = sorted(acc.items(), key=lambda kv: -kv[1])
    return out[:n] if n else out


class KnowledgeBase:
    """Corpus + index. `index_path` is a JSON file written by build_index.py."""

    def __init__(self, index_path: str | Path, dense: bool = True):
        self.index_path = Path(index_path)
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"knowledge index missing: {self.index_path}\n"
                f"run: python -m cadbridge.build_index"
            )
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.chunks = [Chunk.from_dict(c) for c in raw["chunks"]]
        self.bm25 = BM25([c.tokens for c in self.chunks])
        self.version = raw.get("version", 1)
        self.built_at = raw.get("built_at", "")
        self._dense = None
        self._vecs = None
        self._enc_name = raw.get("dense_model")
        if dense and self._enc_name:
            self._try_dense(raw)

    # ----------------------------------------------------------------- dense
    def _try_dense(self, raw: dict) -> None:
        try:
            import numpy as np
        except Exception:
            return
        vecs_path = self.index_path.with_suffix(".vecs.npy")
        if not vecs_path.exists():
            return
        try:
            self._vecs = np.load(vecs_path)
        except Exception:
            return
        try:  # fastembed first (small, onnx, no torch)
            from fastembed import TextEmbedding  # type: ignore

            self._dense = ("fastembed", TextEmbedding(model_name=self._enc_name))
            return
        except Exception:
            pass
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._dense = ("st", SentenceTransformer(self._enc_name))
        except Exception:
            self._vecs = None

    def _embed_query(self, query: str):
        if not self._dense or self._vecs is None:
            return None
        kind, model = self._dense
        try:
            if kind == "fastembed":
                v = list(model.embed([query]))[0]
            else:
                v = model.encode([query], normalize_embeddings=True)[0]
            import numpy as np

            v = np.asarray(v, dtype="float32")
            n = np.linalg.norm(v)
            return v / n if n else v
        except Exception:
            return None

    # ---------------------------------------------------------------- search
    def search(self, query: str, k: int = 6, domain: str | None = None,
               kind: str | None = None, min_score: float = 0.0) -> list[dict[str, Any]]:
        q = tokenize(query)
        if not q and not query.strip():
            return []
        bm = self.bm25.scores(q)
        order_bm = [i for i in sorted(range(len(bm)), key=lambda i: -bm[i])]
        order_bm = [i for i in order_bm][: max(k * 8, 40)]

        order_dense: list[int] = []
        dense_sims: dict[int, float] = {}
        qv = self._embed_query(query)
        if qv is not None:
            try:
                import numpy as np

                sims = self._vecs @ qv
                idx = np.argsort(-sims)[: max(k * 8, 40)]
                order_dense = [int(i) for i in idx]
                dense_sims = {int(i): float(sims[i]) for i in idx}
            except Exception:
                order_dense = []

        if order_dense:
            fused = _rrf([order_bm, order_dense])
            ranked = [i for i, _ in fused]
            fused_score = {i: s for i, s in fused}
        else:
            ranked = order_bm
            fused_score = {}
        if domain:
            ranked = [i for i in ranked if self.chunks[i].domain == domain]
        if kind:
            ranked = [i for i in ranked if self.chunks[i].kind == kind]

        out = []
        for i in ranked:
            c = self.chunks[i]
            sc = fused_score.get(i, 0.0) if fused_score else (bm[i] / (1 + bm[i]) if bm[i] else 0.0)
            if sc < min_score:
                continue
            d = c.to_dict()
            d["score"] = round(sc, 5)
            d["bm25"] = round(bm[i], 4)
            if i in dense_sims:
                d["dense"] = round(dense_sims[i], 4)
            out.append(d)
            if len(out) >= k:
                break
        return out

    def get(self, doc_id: str) -> dict[str, Any] | None:
        for c in self.chunks:
            if c.id == doc_id:
                return c.to_dict()
        return None

    def listing(self) -> list[dict[str, str]]:
        return [{"id": c.id, "domain": c.domain, "kind": c.kind, "title": c.title}
                for c in self.chunks]

    def stats(self) -> dict[str, Any]:
        doms: Counter = Counter(c.domain for c in self.chunks)
        kinds: Counter = Counter(c.kind for c in self.chunks)
        return {"chunks": len(self.chunks), "domains": dict(doms), "kinds": dict(kinds),
                "dense": bool(self._dense), "built_at": self.built_at,
                "index": str(self.index_path)}


_CACHE: dict[str, KnowledgeBase] = {}


def default_index_path() -> Path:
    env = os.environ.get("CADBRIDGE_INDEX")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    return here / "corpus" / "index.json"


def get_kb(index_path: str | Path | None = None) -> KnowledgeBase:
    p = Path(index_path) if index_path else default_index_path()
    key = str(p)
    if key not in _CACHE:
        _CACHE[key] = KnowledgeBase(p)
    return _CACHE[key]
