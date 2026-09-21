"""Create FraudGraph and apply schema + vector attributes. Idempotent: skips if schema already applied; --reset drops first."""
import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tigergraph import spec  # noqa: E402
from tigergraph.client import TG  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--reset", action="store_true", help="DROP the graph first (destroys loaded data)")
args = ap.parse_args()

tg = TG()
G = tg.graph
exists = f"Graph {G}" in tg.gsql("SHOW GRAPH *")

if exists and args.reset:
    print(f"dropping {G} ...")
    tg.gsql(f"DROP GRAPH {G}")
    exists = False
if not exists:
    print(tg.gsql(f"CREATE GRAPH {G}()").strip())

show = tg.gsql(f"SHOW GRAPH {G}", check=False)
if "Transaction(" in show:
    print("schema already applied")
else:
    print("applying schema (~40s) ...")
    out = tg.gsql(spec.schema_job(G), graph=G)
    print(out.strip().splitlines()[-1])

# vectors: attempt every time only if missing (SHOW VERTEX omits vectors, so probe via a marker file in the graph comment)
marker = pathlib.Path(__file__).resolve().parents[1] / "tigergraph" / ".vectors_applied"
if marker.exists() and not args.reset:
    print("vector attributes already applied")
else:
    print("adding vector attributes (~40s) ...")
    out = tg.gsql(spec.vector_job(G), graph=G, check=False)
    print(out.strip().splitlines()[-1])
    if "succeeded" in out.lower() or "completes" in out.lower():
        marker.write_text("ok")
    else:
        print(out[:1500]); sys.exit(1)
print(tg.gsql(f"SHOW GRAPH {G}", check=False)[:300])
