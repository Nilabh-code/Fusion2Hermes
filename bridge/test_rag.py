import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cadbridge.rag import get_kb

kb = get_kb()
print(kb.stats(), "\n")

QUERIES = [
    ("make a servo mount for an SG90 micro servo", {"rec-005", "hw-003"}),
    ("what size hole for an M4 screw", {"hw-001"}),
    ("import a step file into fusion with python", {"fa-002"}),
    ("fillet failed radius too big", {"bd-010"}),
    ("608 bearing press fit pocket tolerance", {"hw-002", "rec-006"}),
    ("open top enclosure shell", {"bd-005"}),
    ("grid of holes spacing on a plate", {"bd-007"}),
    ("press fit clearance for a printed part", {"hw-004"}),
    ("counterbore for a socket head cap screw", {"bd-006", "hw-001"}),
    ("what units does the fusion api use", {"fa-001"}),
    ("hex standoff across flats", {"rec-004", "hw-001"}),
    ("overhang limit and minimum wall for fdm", {"pr-001", "hw-004"}),
    ("how do I verify the volume of my model", {"wf-005", "wf-003"}),
    ("read measurements from an annotated image", {"wf-002"}),
]

hits = 0
for q, want in QUERIES:
    res = kb.search(q, k=5)
    ids = [r["id"] for r in res]
    ok = bool(want & set(ids))
    hits += ok
    top = res[0]["id"] if res else "-"
    print(f"{'PASS' if ok else 'MISS'}  {q!r}\n      top={top} want={sorted(want)} got={ids}")

print(f"\n{hits}/{len(QUERIES)} queries had a wanted chunk in the top 5")
