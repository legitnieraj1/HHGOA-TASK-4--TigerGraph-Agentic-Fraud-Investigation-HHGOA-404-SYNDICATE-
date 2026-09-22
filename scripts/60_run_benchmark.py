"""Phase 8: runs all 20 case_pack.csv cases end to end, writes one answer file per case to repo-root `cases/`
(README: "a folder called cases/ in your repository" -- NOT outputs/cases/, see NOTES.md's README-vs-prompt.md
conflict log), validates each against the answer format, and prints a summary. Idempotent: reruns overwrite.
Usage: 60_run_benchmark.py [case_id ...]  (default: all 20)"""
import json
import pathlib
import sys
import time

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.answer import build  # noqa: E402
from agent.graph import run_case  # noqa: E402
from agent.validate import validate  # noqa: E402
from tigergraph.client import TG  # noqa: E402

OUT = ROOT / "cases"
OUT.mkdir(exist_ok=True)

con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)
rows = con.execute("SELECT case_id, opened_at, trigger_type, trigger_text, flagged_txn_id, card_id, customer_id, "
                   "risk_score FROM case_pack ORDER BY case_id").fetchall()
only = set(sys.argv[1:])
if only:
    rows = [r for r in rows if r[0] in only]

tg = TG()
summary = []
t0 = time.time()
for cid, opened, ttype, ttext, txn, card, cust, risk in rows:
    t1 = time.time()
    try:
        state = run_case(tg, case_id=cid, trigger_type=ttype, trigger_text=ttext, opened_at=str(opened),
                         flagged_txn_id=int(txn), card_id=card, customer_id=cust, risk_score_input=risk)
        answer = build(state)
        problems = validate(answer)
        (OUT / f"{cid}.json").write_text(json.dumps(answer, indent=2, default=str))
        summary.append((cid, answer["case"]["verdict"], answer["case"]["pattern"], answer["case"]["fraud_probability"],
                       answer["sar"]["file"], len(problems), round(time.time() - t1, 1), None))
        status = "OK" if not problems else f"INVALID ({len(problems)})"
        print(f"{cid}  {status:14s} verdict={answer['case']['verdict']:11s} pattern={answer['case']['pattern']:28s} "
             f"p={answer['case']['fraud_probability']:.2f}  sar={answer['sar']['file']}  ({time.time()-t1:.0f}s)", flush=True)
        if problems:
            for pr in problems:
                print(f"    ! {pr}")
    except Exception as e:  # noqa: BLE001 -- one bad case must not kill the whole run
        summary.append((cid, None, None, None, None, None, round(time.time() - t1, 1), f"{type(e).__name__}: {e}"))
        print(f"{cid}  FAILED: {type(e).__name__}: {e}", flush=True)

print(f"\n{'='*70}")
ok = sum(1 for s in summary if s[5] == 0)
invalid = sum(1 for s in summary if s[5] is not None and s[5] > 0)
failed = sum(1 for s in summary if s[7] is not None)
print(f"{len(summary)} cases, {ok} valid, {invalid} invalid, {failed} failed, {time.time()-t0:.0f}s total")
verdicts = {}
for s in summary:
    if s[1]:
        verdicts[s[1]] = verdicts.get(s[1], 0) + 1
print("verdicts:", verdicts)
print("sar filed:", sum(1 for s in summary if s[4]))
(ROOT / "outputs" / "benchmark_summary.json").write_text(json.dumps(
    [{"case_id": s[0], "verdict": s[1], "pattern": s[2], "fraud_probability": s[3], "sar_file": s[4],
      "n_problems": s[5], "latency_s": s[6], "error": s[7]} for s in summary], indent=2))
