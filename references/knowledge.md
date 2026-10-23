# The knowledge base

The corpus is the difference between a model that produces plausible-looking CAD
and one that produces a part that fits. It is small, curated, and **executable**.

`cad_knowledge_search` / `cad_knowledge_get` / `cad_context` read it. The index is
`bridge/cadbridge/corpus/index.json`, built by `python -m cadbridge.build_index`.

## What is in it

| domain | contents |
|--------|----------|
| `build123d` | every public symbol in the installed build123d with its real signature and the first paragraph of its docstring (228 chunks) — signatures are extracted from the installed package, so they cannot drift |
| `recipes` | 13 hand-written complete scripts: plate, tube, hex standoff, enclosure, boss plate, L-bracket, pocket block, slot plate, snap hook, dovetail, knurled knob, threaded boss, engraved text — **every one is executed by the test suite and must yield exactly one valid solid** |
| `hardware` | ISO 273 clearance holes, tap drills, heat-set insert ODs, hex nut across-flats and pocket depths, 608/623/624 bearings, SG90/MG996R/NEMA17 envelopes, shaft/hole press-fit tables, M2–M6 screw head dimensions |
| `printing` | FDM design rules: minimum wall, overhang limits, hole shrinkage, slot clearance, bridging, elephant-foot compensation |
| `fusion` | Fusion-specific facts that bite: the API is in **centimetres**, `importToTarget` rejects the root component, STEP export needs `parentComponent`, how to open a document from code |
| `workflow` | the loop itself: how to read an annotation, when to trust a measurement, the verify-before-push rule, repair heuristics |

Chunk ids are stable and meaningful: `bd-*` build123d, `hw-*` hardware,
`rec-*` recipes, `pr-*` printing, `fa-*` Fusion API, `wf-*` workflow.

## Retrieval

Default is BM25 over the chunk text plus a small title/domain boost, fused with
RRF, no network at query time, no model download. Optional upgrades, used only if
already importable:

- `fastembed` or `sentence-transformers` → dense vectors, hybrid BM25 + dense via RRF
  (`python -m cadbridge.build_index --dense`)
- a cross-encoder → rerank the top 20

`cad_knowledge_stats()` tells you which are active. The 14-query regression suite
(`bridge/test_rag.py`) checks that each query returns the expected chunk ids — it
must stay green, because a retrieval miss is invisible in the final part.

## Adding knowledge

1. Add a chunk to `bridge/cadbridge/corpus/curated.py`:

```python
{
    "id": "hw-005",
    "title": "JST-XH connector cut-outs",
    "domain": "hardware",
    "kind": "rule",              # doc | rule | recipe | api
    "text": "...",               # what a model needs to know, with numbers
}
```

2. If it contains a ```python block, `test_corpus_code.py` will execute it — so
   make it run, produce exactly one solid, and be small.
3. `python -m cadbridge.build_index`
4. `python test_rag.py && python test_corpus_code.py`

Rules for a good chunk:

- **Numbers, not adjectives.** "wall ≥ 1.2 mm at 0.4 mm nozzle" beats "use a
  reasonable wall".
- **State the failure it prevents.** "`Mode.SUBTRACT` as the first object in a
  fresh `BuildSketch` raises `Nothing to subtract from`" is worth more than the
  correct usage alone.
- **One topic per chunk**, ~1–2 KB. Retrieval returns 4–8 of them.
- **Verified against this machine's build123d.** Docstrings and signatures are
  extracted automatically; hand-written API claims must be checked by running them.

## Why build123d and not Fusion tool calls

Every generated script is a single artifact that can be executed and measured:
did it run, is it one solid, is it watertight, does the volume match the hand
calculation, does the bounding box match the annotation. That makes rejection
sampling possible — for dataset generation and for the repair loop. Ninety-three
sequential tool calls give you no such signal; you find out it is wrong when you
look at it.
