"""Phase 4: embed + upsert PolicyDoc chunks (graphrag/chunk.py) and ClosedCase summaries (from closed_cases_history.csv,
already loaded as vertices in Phase 1 -- this just adds the `emb` vector attribute). Idempotent: upsert overwrites.
Usage: 40_seed_memory.py [--only policy|cases]"""
import argparse
import pathlib
import sys
import time

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graphrag.chunk import all_chunks  # noqa: E402
from graphrag.embed import embed  # noqa: E402
from tigergraph.client import TG  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--only", default="")
ap.add_argument("--batch", type=int, default=300)
args = ap.parse_args()
do = lambda name: not args.only or name in args.only.split(",")  # noqa: E731

tg = TG()

if do("policy"):
    chunks = all_chunks()
    vecs = embed([c["text"] for c in chunks])
    payload = {"vertices": {"PolicyDoc": {
        c["chunk_id"]: {"source": {"value": c["source"]}, "section": {"value": c["section"]},
                        "title": {"value": c["title"]}, "text": {"value": c["text"]}, "emb": {"value": v}}
        for c, v in zip(chunks, vecs)}}}
    r = tg.upsert(payload)
    print(f"policy: upserted {len(chunks)} chunks -> {r.get('message', r)}")

if do("cases"):
    con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)
    rows = con.execute("SELECT case_id, customer_id, card_id, outcome, pattern, n_txns, exposure_usd, analyst_notes FROM closed_cases").fetchall()
    print(f"cases: embedding {len(rows)} closed-case summaries ...")
    t0 = time.time()
    summaries = [f"{outcome} {pattern}: {notes}" for (_, _, _, outcome, pattern, _, _, notes) in rows]
    vecs = embed(summaries)
    print(f"  embedded in {time.time() - t0:.0f}s")
    for i in range(0, len(rows), args.batch):
        batch = rows[i:i + args.batch]
        bvecs = vecs[i:i + args.batch]
        payload = {"vertices": {"ClosedCase": {
            r[0]: {"emb": {"value": v}} for r, v in zip(batch, bvecs)}}}
        resp = tg.upsert(payload)
        print(f"  {min(i + args.batch, len(rows))}/{len(rows)} -> {resp.get('message', resp)}")
