"""Node 5: gather_more (conditional loop). Fires a controlled, policy-approved evidence action (policy s.5:
validate with the customer, step-up auth, or ask an analyst) when assess_uncertainty says to continue. The
response is simulated (README: replies are not provided) and logged to evidence_requests with the assumption
stated, then folds back into evidence for the next assess_uncertainty pass. Capped by MAX_ROUNDS in
agent/uncertainty.py, enforced by the conditional edge in agent/graph.py -- this node itself just does one round."""
from agent.tools import actions


def _pick_request_type(bundle: dict) -> str:
    """Which evidence-gathering action fits this case. A device/region cluster -> ask the analyst (they can see
    connected cards); a single ambiguous online txn -> step-up is faster than waiting on the customer; otherwise
    ask the customer directly (README's default path, matches R1's VERIFY_WITH_CUSTOMER)."""
    if (bundle.get("ring") or {}).get("n_cards", 0) >= 3 or bundle.get("fraud_linked_connected_cards"):
        return "analyst_info"
    if bundle["channel"] == "online" and len(bundle["episode"]) == 1:
        return "step_up_auth"
    return "customer_validation"


def run(state: dict) -> dict:
    bundle = state["evidence_bundle"]
    p = state["assessment"]["fraud_probability"]
    step = state["round_no"] + 1
    rtype = _pick_request_type(bundle)

    if rtype == "analyst_info":
        resp = actions.request_analyst_info(bundle, step)
    elif rtype == "step_up_auth":
        resp = actions.request_step_up_auth(p, step)
    else:
        resp = actions.request_customer_validation(p, step)

    requests = list(state.get("evidence_requests", []))
    requests.append({"type": resp.type, "asked_after_step": resp.asked_after_step, "assumed_response": resp.assumed_response})

    evidence = list(state.get("evidence", []))
    evidence.append({"claim": f"Evidence request ({resp.type}): {resp.assumed_response}", "source": "customer" if rtype != "analyst_info" else "graph",
                     "ref": f"evidence_request:{step}", "entity_ids": []})

    out = {"round_no": step, "evidence_requests": requests, "evidence": evidence, "evidence_request_outcome": resp.settles}
    if resp.settles == "confirmed":
        out["customer_confirmed"] = True
    elif resp.settles == "denied":
        out["customer_denied"] = True
    elif resp.settles == "no_reply":
        out["no_reply_24h"] = True
    return out
