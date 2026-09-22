"""Create + install every tigergraph/queries/*.gsql (idempotent: CREATE OR REPLACE). Usage: 35_install_queries.py [name ...]"""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigergraph.client import TG  # noqa: E402

tg = TG()
G = tg.graph
only = set(sys.argv[1:])
files = sorted((ROOT / "tigergraph" / "queries").glob("*.gsql"))
names = []
for f in files:
    if only and f.stem not in only:
        continue
    out = tg.gsql(f.read_text(), graph=G, check=False)
    ok = "Successfully created queries" in out or "successfully created" in out.lower()
    print(f"{'OK  ' if ok else 'FAIL'} create {f.stem}" + ("" if ok else f"\n{out[:1500]}"))
    if ok:
        names.append(f.stem)
if names:
    t = time.time()
    out = tg.gsql("INSTALL QUERY " + ", ".join(names), graph=G, check=False)
    print(out[-900:])
    print(f"install took {time.time() - t:.0f}s")

# Verify: every requested query must show as "# installed", not "# draft" (a truncated/hidden output has bitten
# us once already -- INSTALL QUERY can silently drop a query if IT alone failed while others in the batch succeeded).
show = tg.gsql("SHOW QUERY *", graph=G, check=False)
blocks = show.split("# ")
status = {}
for b in blocks[1:]:
    head, _, rest = b.partition("\n")
    for name in (only or [f.stem for f in files]):
        if f"QUERY {name}(" in rest:
            status[name] = head.strip()
bad = {n: s for n, s in status.items() if s != "installed v2" and not s.startswith("installed")}
target = only or {f.stem for f in files}
missing = target - set(status)
if bad or missing:
    print(f"NOT INSTALLED: {bad} missing={missing}")
    sys.exit(1)
print(f"verified installed: {sorted(status)}")
