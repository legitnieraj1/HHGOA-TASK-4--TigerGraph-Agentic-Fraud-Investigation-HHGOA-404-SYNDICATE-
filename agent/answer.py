"""Builds the answer-file JSON (outputs/ANSWER_FORMAT.md) from a finished CaseState. One function, no
side effects -- scripts/50_run_case.py and scripts/60_run_benchmark.py both call this."""


def build(state: dict) -> dict:
    bundle = state["evidence_bundle"]
    pat = bundle["pattern"]
    a = state["assessment"]
    is_legit = a["verdict"] == "legitimate"

    episode_sorted = sorted(bundle["episode"], key=lambda t: t["ts"])
    affected = [] if is_legit else [str(t["txn"]) for t in episode_sorted]
    first_susp = "" if is_legit else str(episode_sorted[0]["txn"]) if episode_sorted else ""
    device_key = bundle.get("device_key")
    ring = bundle.get("ring") or {}
    connected_devices = [device_key] if device_key and ring.get("n_cards", 0) >= 3 else []

    case = {
        "status": {"fraud": "closed_fraud", "legitimate": "closed_legitimate", "uncertain": "escalated"}[a["verdict"]],
        "verdict": a["verdict"],
        "fraud_probability": round(a["fraud_probability"], 2),
        "pattern": pat.pattern,
        "pattern_description": state.get("pattern_description", ""),
        "affected_txn_ids": affected,
        "first_suspicious_txn_id": first_susp,
        "connected_card_ids": [] if is_legit else bundle.get("fraud_linked_connected_cards", []),
        "connected_device_profiles": [] if is_legit else connected_devices,
        "exposure_usd": 0.0 if is_legit else round(state.get("exposure_usd", 0.0), 2),
        "evidence": state["evidence"],
        "similar_prior_cases": bundle.get("similar_prior_cases", []),
        "summary": state["summary"],
        "written_to_graph": state.get("written_to_graph", False),
        "graph_case_id": state.get("graph_case_id", ""),
    }
    return {
        "case_id": state["case_id"],
        "case": case,
        "evidence_requests": state.get("evidence_requests", []),
        "next_best_actions": {"initial": state.get("nba_initial", []), "final": state.get("nba_final", []),
                              "what_changed": state.get("what_changed", "nothing")},
        "sar": state["sar"],
        "stop_reason": state["stop_reason"],
        "tool_calls": state.get("tool_calls", 0),
        "tokens": state.get("tokens", 0),
        "latency_s": state.get("latency_s", 0.0),
    }
