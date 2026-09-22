"""Node 4: assess_uncertainty. Computes fraud_probability + the stop/continue decision (agent/uncertainty.py).
Deterministic; the LLM never computes this number (spec: "don't let the LLM do the fraud detection"). On the
FIRST pass (round_no == 0, before any evidence_requests exist) it also snapshots next_best_actions.initial --
the answer format requires that snapshot from before any requested evidence came back."""
from detectors.evidence import _pred_scores
from agent.uncertainty import assess
from agent import policy_engine


def run(state: dict) -> dict:
    bundle = state["evidence_bundle"]
    pred = _pred_scores(bundle["episode_txn_ids"])
    a = assess(bundle, bundle["pattern"], pred, state["round_no"], evidence_request_outcome=state.get("evidence_request_outcome"))
    assessment = {
        "fraud_probability": a.fraud_probability, "verdict": a.verdict, "n_independent_evidence": a.n_independent_evidence,
        "should_stop": a.should_stop, "stop_reason": a.stop_reason, "continue_reason": a.continue_reason,
        "single_signal": a.n_independent_evidence <= 1,
    }
    out = {"assessment": assessment}
    if state["round_no"] == 0 and "nba_initial" not in state:
        # customer_report seeds customer_denied=True from the trigger itself (trigger.py), not from a request
        # this node made -- so it must be reflected in nba_initial too, not just nba_final.
        flags = policy_engine.build_flags(bundle, assessment, state["trigger_type"], False,
                                          state.get("customer_confirmed", False), state.get("customer_denied", False))
        rr = policy_engine.evaluate(**flags)
        out["nba_initial"] = [{"action": rec.action, "route": rec.route, "reason": rec.reason} for rec in rr.recommendations]
    return out
