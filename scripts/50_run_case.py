"""Phase 5 check: run one case end to end. Accepts either a case_pack.csv id (HHG-###, the real exam) or a
closed_cases_history.csv id (CC-####, for validation -- "run on a confirmed-fraud closed case and a cleared
closed case, the agent should reach a defensible action on each"). Usage: 50_run_case.py <case_id>"""
import json
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.answer import build  # noqa: E402
from agent.graph import run_case  # noqa: E402
from tigergraph.client import TG  # noqa: E402


def lookup(case_id: str, con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute("SELECT case_id, opened_at, trigger_type, trigger_text, flagged_txn_id, card_id, customer_id, "
                      "risk_score FROM case_pack WHERE case_id = ?", [case_id]).fetchone()
    if row:
        cid, opened, ttype, ttext, txn, card, cust, risk = row
        return dict(case_id=cid, opened_at=str(opened), trigger_type=ttype, trigger_text=ttext,
                   flagged_txn_id=int(txn), card_id=card, customer_id=cust, risk_score_input=risk)
    row = con.execute("SELECT case_id, opened_at, outcome, pattern, card_id, customer_id, first_fraud_txn_id, txn_ids "
                      "FROM closed_cases WHERE case_id = ?", [case_id]).fetchone()
    if not row:
        raise SystemExit(f"{case_id} not found in case_pack.csv or closed_cases_history.csv")
    cid, opened, outcome, pattern, card, cust, first_txn, txn_ids = row
    flagged = first_txn or int(txn_ids.split("|")[0])
    return dict(case_id=cid, opened_at=str(opened), trigger_type="risk_score",
               trigger_text=f"[validation run against closed case {cid}, true outcome={outcome}/{pattern}, not shown to the agent]",
               flagged_txn_id=int(flagged), card_id=card, customer_id=cust, risk_score_input=None)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: 50_run_case.py <case_id>")
    case_id = sys.argv[1]
    con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)
    params = lookup(case_id, con)
    print(f"running {case_id}: trigger={params['trigger_type']} txn={params['flagged_txn_id']} card={params['card_id']}")

    tg = TG()
    state = run_case(tg, **params)
    answer = build(state)

    out_dir = ROOT / "outputs" / "cases_dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_id}.json"
    out_path.write_text(json.dumps(answer, indent=2, default=str))

    print(f"\nverdict={answer['case']['verdict']} pattern={answer['case']['pattern']} "
         f"p={answer['case']['fraud_probability']} exposure=${answer['case']['exposure_usd']}")
    print(f"stop_reason: {answer['stop_reason']}")
    print(f"nba.initial: {[a['action'] for a in answer['next_best_actions']['initial']]}")
    print(f"nba.final:   {[a['action'] for a in answer['next_best_actions']['final']]}")
    print(f"what_changed: {answer['next_best_actions']['what_changed']}")
    print(f"sar.file: {answer['sar']['file']}")
    print(f"evidence_requests: {len(answer['evidence_requests'])}, rounds: {state['round_no']}")
    print(f"tool_calls={answer['tool_calls']} tokens={answer['tokens']} latency_s={answer['latency_s']}")
    print(f"written to {out_path}")
