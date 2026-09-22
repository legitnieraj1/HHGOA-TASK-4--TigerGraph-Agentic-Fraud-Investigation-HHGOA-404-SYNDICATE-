"""Node 1: trigger. Accepts a fraud signal (case_pack row) or an ad-hoc request, opens the case. No graph write
here -- the graph write happens once, in update_memory, with the FULL resolved case (a documented simplification;
see NOTES.md Phase 5).

A `customer_report` trigger's text IS the customer's denial ("I never made this $X purchase" -- README's
case_pack format, and the literal trigger for policy R2 "customer denies the transaction"). Treating it as a
separate thing the agent must go ask about again would be redundant and, worse, wrong: gather_more's simulated
customer-validation response is a function of the agent's OWN probability estimate, not of what the customer
already said -- re-asking could produce a "no_reply" that overrides a denial the customer already gave. So a
customer_report trigger seeds evidence_request_outcome='denied' from round 0, before any evidence is even
gathered; R2 applies from the trigger itself, and no further evidence_requests happens unless the investigation
needs to establish scope (which it still does, via the normal investigate/gather_evidence nodes)."""
import time


def run(state: dict) -> dict:
    is_report = state["trigger_type"] == "customer_report"
    evidence = []
    if is_report:
        evidence.append({"claim": f"Trigger is a customer complaint denying the transaction: {state['trigger_text']!r}",
                         "source": "customer", "ref": "trigger", "entity_ids": [str(state["flagged_txn_id"])]})
    return {
        "round_no": 0, "evidence": evidence, "evidence_requests": [],
        "evidence_request_outcome": "denied" if is_report else None,
        "customer_confirmed": False, "customer_denied": is_report, "no_reply_24h": False,
        "t_start": time.time(), "tool_calls_start": state.get("tool_calls_start", 0),
    }
