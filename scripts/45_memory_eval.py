"""Phase 6 check: does case memory materially change the assessment vs memory disabled? Held-out eval on
confirmed-fraud closed cases (never touches the 20 case_pack cases). Reuses the Phase 2 finding (NOTES.md) that
account_takeover vs out_of_region_use is NOT separable from a single episode's behaviour alone -- exactly the
condition where same-card case memory (apply_memory_prior) should matter, if it matters at all. Writes results
to outputs/memory_eval.json for Phase 9's ACCEPTANCE.md to cite."""
import collections
import json
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from detectors.patterns import classify, apply_memory_prior  # noqa: E402

con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)

rows = con.execute("""SELECT cc.case_id, cc.pattern, cc.card_id, cc.opened_at, t.channel, t.dev_status, t.product, t.addr1
   FROM cc_txn cc JOIN tx t USING(txn) WHERE cc.outcome='confirmed_fraud'""").fetchall()
eps = collections.defaultdict(list)
lab, card, opened = {}, {}, {}
for cid, pat, crd, op, ch, ds, pr, ad in rows:
    eps[cid].append({"channel": ch, "dev_status": ds, "product": pr, "addr1": ad if ad is not None else -1})
    lab[cid], card[cid], opened[cid] = pat, crd, op

prior_map = collections.defaultdict(list)
for cid2, pat2, crd2, op2 in con.execute(
        "SELECT case_id, pattern, card_id, opened_at FROM closed_cases WHERE outcome='confirmed_fraud' ORDER BY opened_at").fetchall():
    prior_map[crd2].append((op2, pat2))


def priors_for(cid):
    seq = [p for (o, p) in prior_map[card[cid]] if o < opened[cid]]
    return list(reversed(seq))  # most-recent-first


# Held-out set: ATO/OOR cases (the ones memory is calibrated to help) with >=1 prior same-card fraud case.
eligible = [cid for cid in eps if lab[cid] in ("account_takeover", "out_of_region_use") and priors_for(cid)]
print(f"eligible held-out cases (ATO/OOR with same-card prior fraud): {len(eligible)}")

ok_no_memory = ok_with_memory = 0
flips = []
for cid in eligible:
    r_no_mem = classify(eps[cid])
    r_with_mem = apply_memory_prior(r_no_mem, priors_for(cid))
    ok_no_memory += (r_no_mem.pattern == lab[cid])
    ok_with_memory += (r_with_mem.pattern == lab[cid])
    if r_no_mem.pattern != r_with_mem.pattern:
        flips.append({"case_id": cid, "true_pattern": lab[cid], "no_memory": r_no_mem.pattern, "with_memory": r_with_mem.pattern,
                     "correct_before": r_no_mem.pattern == lab[cid], "correct_after": r_with_mem.pattern == lab[cid]})

n = len(eligible)
acc_no = ok_no_memory / n
acc_with = ok_with_memory / n
print(f"accuracy WITHOUT memory: {ok_no_memory}/{n} = {acc_no:.3f}")
print(f"accuracy WITH memory:    {ok_with_memory}/{n} = {acc_with:.3f}")
print(f"cases where memory flipped the recommendation: {len(flips)}")
n_fixed = sum(1 for f in flips if f["correct_after"] and not f["correct_before"])
n_broke = sum(1 for f in flips if f["correct_before"] and not f["correct_after"])
print(f"  memory fixed a wrong call: {n_fixed}   memory broke a right call: {n_broke}")

result = {"n_eligible": n, "accuracy_without_memory": round(acc_no, 4), "accuracy_with_memory": round(acc_with, 4),
         "n_flipped": len(flips), "n_memory_fixed": n_fixed, "n_memory_broke": n_broke,
         "sample_flips": flips[:10]}
(ROOT / "outputs" / "memory_eval.json").write_text(json.dumps(result, indent=2))
print("wrote outputs/memory_eval.json")
