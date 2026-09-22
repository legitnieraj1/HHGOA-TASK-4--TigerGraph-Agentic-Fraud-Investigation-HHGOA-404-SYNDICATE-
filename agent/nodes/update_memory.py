"""Node 8: update_memory. Writes the resolved case into the graph (agent/memory.py) so the next investigation
can find it -- the case memory the spec requires. Also finalises bookkeeping (tool_calls, latency) for the
answer file's top-level fields."""
import time

from agent import memory


def run(state: dict, tg) -> dict:
    bundle = state["evidence_bundle"]
    a = state["assessment"]
    status = {"fraud": "closed_fraud", "legitimate": "closed_legitimate", "uncertain": "escalated"}[a["verdict"]]
    device_keys = [d for d in ([bundle.get("device_key")] + list((bundle.get("ring") or {}).get("fraud_linked_cards", []))) if d]
    actions = []
    for i, rec in enumerate(state["nba_final"]):
        actions.append((f"{state['case_id']}-A{i+1}", rec["action"], rec["route"], "final", rec["reason"],
                        "pending_approval" if rec["route"] != "auto" else "executed"))

    graph_case_id = memory.write_case(
        tg, case_id=state["case_id"], trigger_type=state["trigger_type"], status=status, verdict=a["verdict"],
        fraud_probability=a["fraud_probability"], pattern=bundle["pattern"].pattern,
        exposure_usd=state.get("exposure_usd", 0.0), opened_at=state["opened_at"], summary=state["summary"],
        flagged_txn_id=state["flagged_txn_id"], card_id=state["card_id"], episode_txn_ids=bundle["episode_txn_ids"],
        connected_card_ids=bundle.get("fraud_linked_connected_cards", []), device_keys=device_keys, actions=actions,
        similar_prior_case_ids=bundle.get("similar_prior_cases", []),
    )
    return {"written_to_graph": True, "graph_case_id": graph_case_id,
           "tool_calls": tg.calls - state.get("tool_calls_start", 0), "latency_s": round(time.time() - state["t_start"], 1)}
