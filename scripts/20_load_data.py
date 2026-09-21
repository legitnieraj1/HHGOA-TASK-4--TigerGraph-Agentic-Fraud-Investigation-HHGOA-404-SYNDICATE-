"""Chunked, checkpointed, idempotent load of data/export/*.tsv into FraudGraph via loading jobs (POST /restpp/ddl).

Upserts make re-runs safe. Checkpoint: data/export/.checkpoint.json (file -> lines already loaded).
Usage: 20_load_data.py [--only txns,next] [--fresh] [--chunk 10000]"""
import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigergraph import loading  # noqa: E402
from tigergraph.client import TG  # noqa: E402

EXPORT = ROOT / "data" / "export"
CKPT = EXPORT / ".checkpoint.json"
ORDER = ["customers", "cards", "devices", "emails", "regions", "txns", "next", "closed_cases", "involves", "cc_connected"]

ap = argparse.ArgumentParser()
ap.add_argument("--only", default="")
ap.add_argument("--fresh", action="store_true", help="ignore checkpoint")
ap.add_argument("--chunk", type=int, default=10000)
ap.add_argument("--limit", type=int, default=0, help="only first N lines per file (smoke test)")
args = ap.parse_args()

tg = TG()
ckpt = {} if args.fresh or not CKPT.exists() else json.loads(CKPT.read_text())
todo = [n for n in ORDER if not args.only or n in args.only.split(",")]


def check_response(name, r, n_lines):
    if r.get("error"):
        raise SystemExit(f"{name}: load error: {r.get('message')}")
    stats = r["results"][0]["statistics"]["parsingStatistics"]
    valid = stats["fileLevel"].get("validLine", 0)
    bad = {k: v for k, v in stats["fileLevel"].items() if k != "validLine" and v}
    ok_keys = ("typeName", "validObject", "passedCondition", "failedCondition")  # *Condition = our WHERE filters
    obj_bad = [(o.get("typeName"), {k: v for k, v in o.items() if k not in ok_keys and v})
               for grp in ("vertex", "edge") for o in stats["objectLevel"].get(grp, [])
               if any(v for k, v in o.items() if k not in ok_keys)]
    if valid != n_lines or bad or obj_bad:
        raise SystemExit(f"{name}: parsing problem valid={valid}/{n_lines} fileLevel={bad} objectLevel={obj_bad}")


t_all = time.time()
for name in todo:
    path = EXPORT / f"{name}.tsv"
    total = sum(1 for _ in open(path, "rb"))
    if args.limit:
        total = min(total, args.limit)
    done = ckpt.get(name, 0)
    if done >= total:
        print(f"{name}: already loaded ({done:,})", flush=True)
        continue
    t0 = time.time()
    with open(path, "rb") as fh:
        for _ in range(done):
            fh.readline()
        while done < total:
            lines = []
            for _ in range(min(args.chunk, total - done)):
                lines.append(fh.readline())
            payload = b"".join(lines)
            for attempt in range(6):  # gateway 502/504 under load: back off, retry (upserts are idempotent)
                try:
                    r = tg.rest("POST", f"/restpp/ddl/{tg.graph}", params={"tag": f"load_{name}", "filename": "f", "sep": "\t", "eol": "\n"},
                                data=payload, headers={"Content-Type": "text/plain"}, timeout=900)
                    break
                except Exception as ex:  # noqa: BLE001
                    wait = 20 * (attempt + 1)
                    print(f"{name}: chunk at {done:,} failed ({str(ex)[:80]}), retry {attempt + 1}/6 in {wait}s", flush=True)
                    time.sleep(wait)
            else:
                raise SystemExit(f"{name}: giving up at {done:,}")
            check_response(name, r, len(lines))
            done += len(lines)
            ckpt[name] = done
            CKPT.write_text(json.dumps(ckpt))
            rate = done / max(time.time() - t0, 1e-6)
            print(f"{name}: {done:,}/{total:,} ({rate:,.0f} rows/s)", flush=True)
print(f"posted all in {time.time() - t_all:.0f}s. Counts lag (Kafka); run scripts/25_verify_load.py")
