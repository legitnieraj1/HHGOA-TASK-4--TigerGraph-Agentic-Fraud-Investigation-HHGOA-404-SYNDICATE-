"""Mock action layer (spec: 'real-world side effects are simulated via mock APIs that log to the case and the
graph'). Two categories:

1. Evidence-gathering actions (policy s.5): ask the customer to validate a transaction, request step-up auth,
   or request analyst info. Customer/analyst replies are NOT provided (README) -- simulated deterministically
   here (same inputs -> same output every run, satisfying prompt.md's "determinism for the demo" guardrail) from
   the agent's OWN current fraud-probability estimate, never from a hidden label. The assumption is always
   recorded, per README: "state the assumption you made in evidence_requests".

2. Policy actions (the 14 identifiers in data/policy/fraud_policy.md s.1). Only 'auto'-route actions actually
   "execute" here (log an Action node + a case-log line); L1/L2 actions are recorded as pending, never executed,
   per policy s.2 -- this module enforces that gate, not just the policy_engine's routing table."""
import dataclasses

from agent import policy_engine

CUSTOMER_CONFIRM_BELOW = 0.30   # a customer would recognise and confirm their own low-suspicion activity
CUSTOMER_DENY_ABOVE = 0.60      # strong evidence already -> simulate a denial, consistent with that evidence


@dataclasses.dataclass
class EvidenceResponse:
    type: str
    asked_after_step: int
    assumed_response: str
    settles: str  # "confirmed" | "denied" | "no_reply" | "inconclusive"


def request_customer_validation(current_fraud_probability: float, step: int) -> EvidenceResponse:
    if current_fraud_probability >= CUSTOMER_DENY_ABOVE:
        resp = "Customer states they did not make these purchases and still has the card in their possession."
        return EvidenceResponse("customer_validation", step, resp, "denied")
    if current_fraud_probability <= CUSTOMER_CONFIRM_BELOW:
        resp = "Customer confirms they made the purchase(s) themselves."
        return EvidenceResponse("customer_validation", step, resp, "confirmed")
    resp = ("No response from the customer within 24 hours of the validation request "
           "(assumed per policy s.5: replies are not provided in this exercise; simulated as non-response for a mid-range case).")
    return EvidenceResponse("customer_validation", step, resp, "no_reply")


def request_step_up_auth(current_fraud_probability: float, step: int) -> EvidenceResponse:
    """Real step-up auth is a synchronous, binary real-world outcome (no natural 'no reply'), but simulating
    EVERY probability above CUSTOMER_CONFIRM_BELOW as an outright denial was a real bug: it collapsed the whole
    genuinely-ambiguous middle band (e.g. p=0.32, barely past the confirm threshold) into "denied", which then
    pushes probability toward fraud -- circular, and exactly the cases README calls "half legitimate" got
    pushed the wrong way. Mirrors request_customer_validation's three-way split instead."""
    if current_fraud_probability <= CUSTOMER_CONFIRM_BELOW:
        resp = "Customer completed step-up authentication (OTP) successfully; activity confirmed as the account owner's."
        return EvidenceResponse("step_up_auth", step, resp, "confirmed")
    if current_fraud_probability >= CUSTOMER_DENY_ABOVE:
        resp = "Customer did not complete step-up authentication; the session was abandoned."
        return EvidenceResponse("step_up_auth", step, resp, "denied")
    resp = ("Customer completed step-up authentication after a retry (weak signal on the underlying evidence; "
           "assumed per policy s.5 as a borderline case, neither a clean confirmation nor a clear denial).")
    return EvidenceResponse("step_up_auth", step, resp, "inconclusive")


def request_analyst_info(evidence_bundle: dict, step: int) -> EvidenceResponse:
    """Deterministic 'analyst reply' synthesized from the graph evidence already gathered (not invented facts)."""
    ring = evidence_bundle.get("ring") or {}
    connected = evidence_bundle.get("fraud_linked_connected_cards") or []
    if connected:
        resp = (f"Analyst confirms: {len(connected)} other card(s) linked through this device profile have prior "
               f"confirmed-fraud cases; recommends treating this as coordinated.")
        settles = "denied"
    elif ring.get("n_cards", 0) >= 5:
        resp = f"Analyst notes the device profile is shared across {ring['n_cards']} cards this period; escalation warranted."
        settles = "denied"
    else:
        resp = "Analyst reviewed the case file and found no additional cards or devices connected to this activity."
        settles = "inconclusive"
    return EvidenceResponse("analyst_info", step, resp, settles)


REQUESTERS = {"customer_validation": request_customer_validation, "step_up_auth": request_step_up_auth,
             "analyst_info": request_analyst_info}


@dataclasses.dataclass
class ExecutedAction:
    action: str
    route: str
    executed: bool
    reason: str
    log: str


def execute(rec: policy_engine.Recommendation, exposure_usd: float) -> ExecutedAction:
    """Simulate carrying out ONE recommended action. Only 'auto' actions actually execute; L1/L2 are recorded
    pending human approval and never executed here, matching policy s.2 exactly."""
    executable = policy_engine.is_executable(rec.route)
    if not executable:
        return ExecutedAction(rec.action, rec.route, False, rec.reason,
                              f"PENDING {rec.route} approval -- not executed by the agent (policy s.2)")
    sim = {
        "ALLOW_TRANSACTION": "Transaction allowed to stand.",
        "MONITOR_CARD": "Card placed under elevated monitoring for 72 hours.",
        "MONITOR_CONNECTED_CARDS": "Connected cards placed under elevated monitoring for 72 hours.",
        "WARN_CUSTOMER": "Informational message sent to the customer.",
        "VERIFY_WITH_CUSTOMER": "Validation request sent to the customer.",
        "STEP_UP_AUTH": "Step-up authentication challenge issued.",
        "GENERATE_REPORT": "Internal investigation report generated (no case opened).",
        "CREATE_CASE": "Internal fraud case opened and evidence attached.",
        "ESCALATE_TO_ANALYST": "Case handed to a human analyst with the evidence bundle.",
        "CLOSE_NO_FRAUD": "Alert closed as legitimate.",
    }.get(rec.action, "Executed.")
    return ExecutedAction(rec.action, rec.route, True, rec.reason, sim)
