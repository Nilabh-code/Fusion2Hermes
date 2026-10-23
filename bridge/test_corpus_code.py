"""Every code block in the knowledge corpus must actually run.

This is the corpus quality gate: a recipe that raises would teach the model to
raise. Run from bridge/:  python test_corpus_code.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cadbridge.corpus.curated import CHUNKS
from cadbridge.runner import run_code

blocks = []
for c in CHUNKS:
    for i, body in enumerate(re.findall(r"```python\s*\n(.*?)```", c["text"], re.S)):
        if "from build123d import" in body:
            blocks.append((c["id"], i, body))

print(f"{len(blocks)} runnable code blocks in the corpus\n")
fails = 0
for cid, i, body in blocks:
    r = run_code(body, out_dir=None, timeout=180)
    if r["ok"] and r["solids"] == 1 and r["valid"]:
        print(f"PASS {cid}#{i}  vol={r['volume']:.1f} mm3  solids={r['solids']} "
              f"bbox={[round(v,2) for v in r['bbox']]} valid={r['valid']}")
    else:
        fails += 1
        detail = r.get("error") or ""
        first = detail.strip().splitlines()
        why = (f"solids={r.get('solids')} valid={r.get('valid')}" if r["ok"]
               else (first[-1][:220] if first else "failed"))
        print(f"FAIL {cid}#{i}  {why}")
        if len(first) > 1 and not r["ok"]:
            print(f"      {first[0][:200]}")
print(f"\n{len(blocks) - fails}/{len(blocks)} code blocks executed")
sys.exit(1 if fails else 0)
