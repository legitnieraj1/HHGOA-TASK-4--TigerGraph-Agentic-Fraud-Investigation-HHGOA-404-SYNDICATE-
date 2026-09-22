"""Fraud-probability scoring and the stop/continue decision (policy s.0, s.6). Deterministic -- combines the
calibrated propensity model (detectors/propensity.py) with the pattern classifier's `evidence_strength`
(detectors/patterns.py -- NOT `confidence`, which answers a different question: "if this is fraud, which
pattern"; evidence_strength answers "does matching this pattern indicate fraud at all", and composition-only
matches like "an online purchase happened" score low on it even at high confidence -- see detectors/patterns.py's
PatternResult docstring and NOTES.md Phase 8 for the bug this replaced: blending raw pattern `confidence` made
every online purchase look like default fraud evidence, since the composition rules fire on ANY episode of that
shape). Weighted per pattern by how well propensity is known to track it (Phase 2 calibration: propensity is
well-calibrated for the two card-not-present patterns and card_testing, but "blind" to in-person ATO/OOR and to
undocumented structuring/ring -- see NOTES.md). The LLM never touches this number."""
from dataclasses import dataclass

# weight on propensity vs pattern evidence_strength, by pattern (NOTES.md "Phase 2 calibration findings"):
# CNP/CNP-new-device/card_testing: propensity median 0.77/0.55/0.69 on their true episodes -- trust it.
# account_takeover/out_of_region_use: propensity median 0.36/0.34 (blind to in-person fraud) -- trust the pattern call.
# undocumented (structuring/ring): propensity 0.01-0.54 (fully blind, not designed to see it) -- trust the pattern call,
#   which is itself calibrated at 0 false positives / precise matches in Phase 2.
PROPENSITY_WEIGHT = {
    "card_not_present_fraud": 0.7, "card_not_present_new_device": 0.7, "card_testing": 0.6,
    "account_takeover": 0.3, "out_of_region_use": 0.3,
    "undocumented": 0.1, "none": 0.5,
}

STOP_HIGH = 0.85
STOP_LOW = 0.15
MIN_INDEPENDENT_EVIDENCE = 2
MAX_ROUNDS = 3  # prompt.md guardrail: cap the evidence loop, guarantee termination


@dataclass
class Assessment:
    fraud_probability: float
    verdict: str          # fraud | legitimate | uncertain
    n_independent_evidence: int
    should_stop: bool
    stop_reason: str
    continue_reason: str = ""


def episode_propensity(episode_txn_ids, pred_scores: dict) -> float:
    """Mean calibrated propensity (p_cal) over the episode's transactions. pred_scores: {txn_id: p_cal},
    already looked up by detectors/evidence.py from the local `pred` table."""
    vals = [pred_scores[t] for t in episode_txn_ids if t in pred_scores]
    return sum(vals) / len(vals) if vals else 0.0


def count_independent_evidence(evidence_bundle: dict, pattern_result) -> int:
    """How many independent signals point the same direction. Each of these is a distinct data source:
    propensity model, pattern-composition rule, case memory (same-card prior or semantic similar-case),
    device/region clustering, and (once gathered) a customer/analyst response."""
    n = 0
    if evidence_bundle.get("episode_txn_ids"):
        n += 1  # propensity signal exists
    if pattern_result.pattern != "none":
        n += 1  # a pattern actually matched
    if evidence_bundle.get("prior_fraud_patterns") or evidence_bundle.get("similar_prior_cases"):
        n += 1  # case memory
    if evidence_bundle.get("fraud_linked_connected_cards"):
        n += 1  # device/region clustering to other confirmed fraud
    if evidence_bundle.get("customer_response_received"):
        n += 1  # a verification response
    return n


def assess(evidence_bundle: dict, pattern_result, pred_scores: dict, round_no: int,
          evidence_request_outcome: str | None = None) -> Assessment:
    """evidence_request_outcome: None (no request made yet) | "confirmed" | "denied" | "no_reply" | "inconclusive".
    Once ANY evidence request has been made and answered, this simulator's response is a pure function of the
    evidence already gathered -- asking the same or a different question again cannot produce new information
    (it's not a real customer, there's nothing further to learn). So every non-None outcome is treated as
    terminal: policy R4 explicitly defines the action for "no reply" (MONITOR_CARD + DECLINE_TRANSACTION,
    conditionally escalate) rather than asking again, and "inconclusive" falls to policy s.6's third stop
    condition ("further steps are unlikely to change the decision"). Only "confirmed"/"denied" change the
    probability itself; "no_reply"/"inconclusive" stop the loop without moving it."""
    pat = pattern_result.pattern
    p_prop = episode_propensity(evidence_bundle["episode_txn_ids"], pred_scores)
    w = PROPENSITY_WEIGHT.get(pat, 0.5)
    p = w * p_prop + (1 - w) * pattern_result.evidence_strength

    # Proportional blend, not a hard clamp: a denial/confirmation is strong evidence, but a flat clamp (e.g.
    # max(p, 0.82)) would collapse every denied case to the identical probability regardless of how strong the
    # underlying evidence already was -- losing exactly the calibration nuance the README asks for ("be honest;
    # this is scored for calibration"). Moving proportionally toward the extreme keeps cases ordered by their
    # underlying evidence strength while still reflecting that a direct response is decisive.
    if evidence_request_outcome == "confirmed":
        p = p * 0.4
    elif evidence_request_outcome == "denied":
        p = p + (1 - p) * 0.6
    p = max(0.01, min(0.99, p))

    n_ev = count_independent_evidence(evidence_bundle, pattern_result)
    if evidence_request_outcome is not None:
        n_ev = max(n_ev, MIN_INDEPENDENT_EVIDENCE)  # a direct response (of any kind) is itself corroboration

    if evidence_request_outcome in ("confirmed", "denied"):
        return Assessment(p, "legitimate" if evidence_request_outcome == "confirmed" else "fraud", n_ev, True,
                          f"verification response settled the question ({evidence_request_outcome})")
    if evidence_request_outcome == "no_reply":
        verdict = "fraud" if p >= 0.5 else "legitimate" if p <= 0.3 else "uncertain"
        return Assessment(p, verdict, n_ev, True, "R4: no reply within 24 hours of the validation request")
    if evidence_request_outcome == "inconclusive":
        verdict = "fraud" if p >= 0.5 else "legitimate" if p <= 0.3 else "uncertain"
        return Assessment(p, verdict, n_ev, True, "the requested evidence came back inconclusive; further steps are unlikely to change the decision")
    if p >= STOP_HIGH and n_ev >= MIN_INDEPENDENT_EVIDENCE:
        return Assessment(p, "fraud", n_ev, True, f"fraud probability {p:.2f} >= {STOP_HIGH}, {n_ev} independent evidence sources")
    if p <= STOP_LOW and n_ev >= MIN_INDEPENDENT_EVIDENCE:
        return Assessment(p, "legitimate", n_ev, True, f"fraud probability {p:.2f} <= {STOP_LOW}, {n_ev} independent evidence sources")
    if round_no >= MAX_ROUNDS:
        return Assessment(p, "uncertain", n_ev, True,
                          f"reached the evidence-gathering round cap ({MAX_ROUNDS}) without a confident answer; escalating rather than looping forever")
    verdict = "fraud" if p >= 0.5 else "legitimate" if p <= 0.3 else "uncertain"
    return Assessment(p, verdict, n_ev, False, "", continue_reason=f"fraud probability {p:.2f} not extreme enough or only {n_ev} evidence source(s); gathering more")
