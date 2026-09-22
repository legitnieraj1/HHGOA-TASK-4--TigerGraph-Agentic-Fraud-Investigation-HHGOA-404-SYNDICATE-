"""Node 6: next_best_action. Computes the FINAL recommendation (after any evidence_requests) and executes every
'auto'-route action via the mock action layer; L1/L2 actions are recorded pending, never executed (policy s.2).
nba_initial was already captured by assess_uncertainty's first pass; this node adds nba_final + what_changed."""
from agent import policy_engine
from agent.tools import actions


def run(state: dict) -> dict:
    bundle = state["evidence_bundle"]
    flags = policy_engine.build_flags(bundle, state["assessment"], state["trigger_type"], state.get("no_reply_24h", False),
                                      state.get("customer_confirmed", False), state.get("customer_denied", False))
    rr = policy_engine.evaluate(**flags)
    nba_final = [{"action": rec.action, "route": rec.route, "reason": rec.reason} for rec in rr.recommendations]

    executed = [actions.execute(rec, flags["exposure_usd"]) for rec in rr.recommendations]

    initial = state.get("nba_initial", nba_final)
    if [x["action"] for x in initial] == [x["action"] for x in nba_final]:
        what_changed = "nothing"
    else:
        added = [x["action"] for x in nba_final if x["action"] not in {i["action"] for i in initial}]
        dropped = [x["action"] for x in initial if x["action"] not in {f["action"] for f in nba_final}]
        last_req = state["evidence_requests"][-1] if state.get("evidence_requests") else None
        settled_negative = state.get("customer_denied") and last_req
        if settled_negative and last_req["type"] == "step_up_auth":
            reason = "the customer failed to complete step-up authentication"
        elif settled_negative and last_req["type"] == "analyst_info":
            reason = "the analyst confirmed a connection to other confirmed-fraud activity"
        elif state.get("customer_denied"):
            reason = "the customer denied the transaction"
        elif state.get("customer_confirmed"):
            reason = "the customer confirmed the transaction"
        elif state.get("evidence_requests"):
            reason = "the requested evidence came back inconclusive/no-reply"
        else:
            reason = "further evidence changed the assessment"
        parts = [f"{reason}, raising probability to {state['assessment']['fraud_probability']:.2f}" if state.get("customer_denied")
                else f"{reason} (probability {state['assessment']['fraud_probability']:.2f})"]
        if added:
            parts.append(f"added {', '.join(added)}")
        if dropped:
            parts.append(f"dropped {', '.join(dropped)}")
        what_changed = "; ".join(parts) + "."

    return {"nba_final": nba_final, "what_changed": what_changed, "exposure_usd": flags["exposure_usd"],
           "executed_log": [{"action": e.action, "route": e.route, "executed": e.executed, "log": e.log} for e in executed]}
