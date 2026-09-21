"""Reconcile FraudGraph counts against data/export (polls because ingest is eventually consistent). Exit 1 on mismatch."""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigergraph import loading  # noqa: E402
from tigergraph.client import TG  # noqa: E402

E = ROOT / "data" / "export"


def lines(n):
    return sum(1 for _ in open(E / f"{n}.tsv", "rb"))


def nonempty(fname, col):
    return sum(1 for l in open(E / f"{fname}.tsv", encoding="utf-8") if l.rstrip("\n").split("\t")[col] != "")


I = loading.IDX
exp_v = {"Customer": lines("customers"), "Card": lines("cards"), "Transaction": lines("txns"), "DeviceProfile": lines("devices"),
         "EmailDomain": lines("emails"), "BillingRegion": lines("regions"), "ClosedCase": lines("closed_cases")}
exp_e = {"OWNS": lines("cards"), "MADE": lines("txns"), "NEXT": lines("next"), "INVOLVES": lines("involves"),
         "CC_ON_CARD": lines("closed_cases"), "CC_CONNECTED_TO": lines("cc_connected"),
         "FROM_DEVICE": nonempty("txns", loading.IDX_DEVICE_KEY), "BILLED_IN": nonempty("txns", loading.IDX_REGION),
         "PURCHASER_EMAIL": nonempty("txns", I["p_email"]), "RECIPIENT_EMAIL": nonempty("txns", I["r_email"])}

tg = TG()
for attempt in range(40):
    v = {x["v_type"]: x["count"] for x in tg.stats()["results"]}
    e = {x["e_type"]: x["count"] for x in tg.edge_stats()["results"]}
    bad = [(k, exp, v.get(k)) for k, exp in exp_v.items() if v.get(k) != exp] + \
          [(k, exp, e.get(k)) for k, exp in exp_e.items() if e.get(k) != exp]
    if not bad:
        break
    print(f"[{attempt}] waiting, {len(bad)} mismatched: {bad[:4]}", flush=True)
    time.sleep(15)
print("vertices:", {k: v.get(k) for k in exp_v})
print("edges   :", {k: e.get(k) for k in exp_e})
print("RECONCILED OK" if not bad else f"MISMATCH: {bad}")
sys.exit(1 if bad else 0)
