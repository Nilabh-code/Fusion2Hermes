# cadbridge

Turn a marked-up photo into a verified, printable part — and put it in Fusion 360.

Three things, one MCP server:

| piece | what it does |
|-------|--------------|
| **knowledge** | 299-chunk retrieval corpus: build123d 0.13 API (extracted from the installed package, so signatures are real), 16 executable recipes, hardware tables (ISO 273 clearance, bearings, servo/stepper envelopes), FDM design rules, Fusion API notes, workflow rules. BM25 by default, hybrid BM25+dense if `fastembed` is installed. |
| **canvas** | a local page where you drop a photo, trace the outline, mark hole centres, draw dimension lines, and calibrate one line to a real length. Everything you draw comes back in millimetres, plus a composite PNG for the vision model. |
| **runner** | executes the generated build123d script in a separate process and reports the *measured* volume, bounding box, solid count and validity, then exports STEP/STL/SVG. Nothing is accepted on faith. |

Plus `fusion_push_step`, which imports the STEP into the running Fusion 360 document
over the add-in socket this repo already installs.

## The loop

```
photo ──▶ canvas ──▶ {shapes in mm} ──▶ knowledge ──▶ build123d script
                                                        │
                        ┌───────────────────────────────┘
                        ▼
                  cad_run_code  ──► volume/bbox/solids ──► mismatch? ──▶ repair
                        │
                        └──► STEP ──► fusion_push_step ──► Fusion 360
```

Nothing reaches Fusion until it has been executed and measured. That is the point:
the failure mode of LLM CAD is a script that *looks* right and silently builds the
wrong thing, and a volume/bbox check catches most of those.

## Install

```bash
cd bridge
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e .
.venv/Scripts/python.exe -m cadbridge.build_index        # add --dense for embeddings
.venv/Scripts/python.exe -m cadbridge.cli status
```

Register with Hermes (one command; `scripts/setup.py` in the repo root does this for you):

```bash
hermes mcp add cadbridge \
  --command "<abs path to bridge/.venv/Scripts/python.exe>" \
  --args -m cadbridge.server
```

## Use it

```bash
# mark up a photo, get millimetres back
cadbridge canvas --image servo.jpg --prompt "servo mount, 3 mm walls" --out ann.json

# verify a script and export STEP/STL
cadbridge run examples/servo_mount.py --out out --expect-volume 3438.6

# put it in Fusion
cadbridge push out/part.step --clear

# drive any OpenAI-compatible model through the whole loop, with repair retries
cadbridge agent --annotate servo.jpg --prompt "servo mount" \
    --base-url http://127.0.0.1:8080/v1 --model qwen3-coder --push
```

## MCP tools

| tool | purpose |
|------|---------|
| `cad_knowledge_search` | query the corpus, returns scored chunks |
| `cad_knowledge_get` | full chunk by id |
| `cad_knowledge_stats` | corpus size / domains / whether dense is active |
| `cad_context` | retrieve + format a briefing block for a model with no tool access |
| `canvas_open` | open the canvas, optionally with an image |
| `canvas_wait` | block until the user submits; returns mm annotations |
| `canvas_status` / `canvas_close` | poll / drop a session |
| `cad_run_code` | execute build123d, measure, export, optional `expect_volume`/`expect_bbox` verdict |
| `fusion_push_step` | import a STEP into the active Fusion document |
| `fusion_status` | is the add-in socket alive, what document is open |

## Design rules the corpus enforces

- one solid named `part`, millimetres, Z up, sitting on Z=0
- every dimension traceable to the annotation, the request, or a hardware table
- cutters longer than the material, fillets capped at a quarter of the smallest face
- holes oversized per the ISO table, not per the photo
- measure, don't trust: the volume must match a hand calculation before export

## Tests

```bash
python test_corpus_code.py     # every recipe in the corpus executes to one valid solid
python test_canvas_e2e.py      # real browser + real mouse + mm round trip
python test_agent_loop.py      # broken script -> feedback -> repaired script
python test_pipeline.py        # script -> verify -> STEP -> inside Fusion
```

MIT. See the repo root `LICENSE` and `NOTICE.md`.
