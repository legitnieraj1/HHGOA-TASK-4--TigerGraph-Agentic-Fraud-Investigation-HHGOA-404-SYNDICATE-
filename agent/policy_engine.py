"""Maps actions -> approval route, and evaluates policy rules R1-R10 against case state to produce a recommended
action list. Deterministic; matches data/policy/fraud_policy.md exactly (also chunked+embedded in
graphrag/chunk.py for retrieval, but THIS module is the source of truth the agent's decisions actually run on --
retrieval is for citation/explanation, not for computing the routing table itself).

Policy s.2: 'auto' actions the agent may execute; L1/L2 actions are recommended, with the route stated, and wait
for a human. This module never executes anything -- agent/tools/actions.py does that, gated by is_executable()."""
from dataclasses import dataclass, field

AUTO = "auto"
L1 = "L1"
L2 = "L2"

# Section 2: approval routing. BLOCK_CARD and FILE_REPORT/BLOCK_ALL_CARDS/DECLINE_TRANSACTION need exposure/context,
# handled in route_for_block_card(); this table covers every OTHER action's fixed route.
FIXED_ROUTE = {
    "ALLOW_TRANSACTION": AUTO, "MONITOR_CARD": AUTO, "MONITOR_CONNECTED_CARDS": AUTO, "WARN_CUSTOMER": AUTO,
    "VERIFY_WITH_CUSTOMER": AUTO, "STEP_UP_AUTH": AUTO, "GENERATE_REPORT": AUTO, "CREATE_CASE": AUTO,
    "ESCALATE_TO_ANALYST": AUTO, "CLOSE_NO_FRAUD": AUTO,
    "DECLINE_TRANSACTION": L1,
    "BLOCK_ALL_CARDS": L2, "FILE_REPORT": L2,
}
BLOCK_CARD_L1_MAX_EXPOSURE = 2500.0  # R2.2: BLOCK_CARD is L1 up to $2,500, L2 above


def route_for(action: str, exposure_usd: float = 0.0) -> str:
    if action == "BLOCK_CARD":
        return L1 if exposure_usd <= BLOCK_CARD_L1_MAX_EXPOSURE else L2
    if action not in FIXED_ROUTE:
        raise ValueError(f"unknown action {action!r}; must be one of the policy's 14 action identifiers")
    return FIXED_ROUTE[action]


def is_executable(route: str) -> bool:
    """Policy s.2: only 'auto' actions may be executed by the agent."""
    return route == AUTO


@dataclass
class Recommendation:
    action: str
    route: str
    reason: str  # must cite the rule number (policy s.7)


@dataclass
class RuleResult:
    recommendations: list = field(default_factory=list)
    fired_rules: list = field(default_factory=list)

    def add(self, action, reason, exposure_usd=0.0):
        """De-duplicates by action: more than one rule (e.g. R6 and R9) can independently recommend the same
        action -- the answer format wants each action once, ordered by what happens first, so a second recommend
        of an already-present action merges its reason onto the first instead of appending a duplicate."""
        existing = next((r for r in self.recommendations if r.action == action), None)
        if existing:
            existing.reason = f"{existing.reason}; also {reason}"
            return
        route = route_for(action, exposure_usd)
        self.recommendations.append(Recommendation(action, route, reason))

    def has(self, action):
        return any(r.action == action for r in self.recommendations)


def evaluate(*, fraud_probability: float, exposure_usd: float, single_signal: bool, verdict: str,
            customer_confirmed: bool, customer_denied: bool, no_reply_24h: bool,
            pending_auth: bool, purchase_over_100_cleared: bool, is_card_testing: bool,
            shared_origin: dict | None, disputed_matches_recurring: bool, is_undocumented_coordinated: bool,
            evidence_conflicts: bool, confirmed_fraud_card_count: int, credentials_confirmed_compromised: bool) -> RuleResult:
    """Runs the rules that apply given the current case state. Callers run this twice per case -- once before any
    evidence_requests (nba_initial) and once after simulated responses (nba_final), per the answer format."""
    r = RuleResult()

    # R3 / R2 / R4: only meaningful once a verification response exists (round_no > 0 in practice, but the
    # flags are only ever True after gather_more sets them).
    if customer_confirmed:
        r.add("CLOSE_NO_FRAUD", "R3: customer confirmed the transaction")
        r.fired_rules.append("R3")
        return r  # R3 settles it; nothing else to recommend
    if customer_denied:
        r.add("BLOCK_CARD", "R2: customer denied the transaction", exposure_usd)
        r.add("CREATE_CASE", "R2")
        if exposure_usd > 1000 or shared_origin:
            r.add("FILE_REPORT", "R2: exposure exceeds $1,000 or the case connects to a shared device/other card's fraud")
        r.fired_rules.append("R2")
    elif no_reply_24h:
        r.add("MONITOR_CARD", "R4: no reply within 24 hours")
        if pending_auth:
            r.add("DECLINE_TRANSACTION", "R4: pending authorization, no reply within 24 hours", exposure_usd)
        if exposure_usd > 500:
            r.add("ESCALATE_TO_ANALYST", "R4: exposure exceeds $500")
        r.fired_rules.append("R4")
    elif disputed_matches_recurring:
        r.add("CREATE_CASE", "R7: disputed charge matches the cardholder's own recurring pattern")
        r.add("VERIFY_WITH_CUSTOMER", "R7")
        r.add("WARN_CUSTOMER", "R7")
        r.fired_rules.append("R7")
    else:
        # R1: verify before blocking on a weak (single-signal) case
        if single_signal and fraud_probability < 0.70:
            r.add("VERIFY_WITH_CUSTOMER", f"R1: single signal, fraud probability {fraud_probability:.2f} < 0.70")
            r.fired_rules.append("R1")
        # R5: card testing
        if is_card_testing:
            r.add("DECLINE_TRANSACTION", "R5: card-testing sequence observed", exposure_usd)
            r.add("STEP_UP_AUTH", "R5")
            if purchase_over_100_cleared:
                r.add("BLOCK_CARD", "R5: a purchase over $100 has already cleared", exposure_usd)
            r.fired_rules.append("R5")
        # R6: shared origin (device profile / billing region / recipient email) across several cards
        if shared_origin:
            name = shared_origin.get("kind", "shared element")
            r.add("CREATE_CASE", f"R6: shared origin ({name}) across multiple cards")
            r.add("FILE_REPORT", "R6")
            r.add("MONITOR_CONNECTED_CARDS", "R6: every card sharing the origin")
            r.fired_rules.append("R6")
        # R9: undocumented but coordinated/repeated abuse
        if is_undocumented_coordinated:
            r.add("CREATE_CASE", "R9: activity fits no documented pattern but shows coordinated/repeated abuse")
            r.add("FILE_REPORT", "R9")
            r.add("ESCALATE_TO_ANALYST", "R9")
            r.fired_rules.append("R9")
        # R8: uncertain and exposed, or evidence conflicts
        if (verdict == "uncertain" and exposure_usd > 500) or evidence_conflicts:
            r.add("ESCALATE_TO_ANALYST", "R8: verdict uncertain and exposure exceeds $500, or evidence conflicts")
            r.fired_rules.append("R8")

    # if nothing at all fired and this isn't a dispute/verification path, and probability is low: legitimate
    if not r.recommendations:
        if fraud_probability <= 0.15:
            r.add("CLOSE_NO_FRAUD", f"fraud probability {fraud_probability:.2f} is low; no rule indicates otherwise")
        else:
            r.add("MONITOR_CARD", f"fraud probability {fraud_probability:.2f}; no specific rule fired, default to monitoring")

    # R10 guard: never recommend BLOCK_ALL_CARDS unless the gate is met (defensive; nothing above proposes it directly)
    if r.has("BLOCK_ALL_CARDS") and not (confirmed_fraud_card_count >= 2 or credentials_confirmed_compromised):
        r.recommendations = [x for x in r.recommendations if x.action != "BLOCK_ALL_CARDS"]

    return r


def episode_exposure(episode: list) -> float:
    """Exposure = sum of absolute amounts of every txn identified as part of the episode (policy s.4)."""
    return round(sum(abs(t["amount"]) for t in episode), 2)


def build_flags(bundle: dict, assessment: dict, trigger_type: str, no_reply_24h: bool,
                customer_confirmed: bool, customer_denied: bool) -> dict:
    """Derives evaluate()'s keyword args from the evidence bundle + assessment, so assess_uncertainty (initial
    pass) and next_best_action (final pass) compute the SAME way. Two documented, honest simplifications given
    what this dataset actually provides (NOTES.md Phase 5):
    - R7 (disputed charge matches a recurring pattern) can never fire: the dataset has no merchant identity,
      only a product CATEGORY code, so "same merchant, same amount, monthly" isn't detectable.
    - `pending_auth` is proxied by trigger_type == 'risk_score' (fires before settlement) vs customer_report/
      analyst_request (fires after the customer already saw a settled transaction) -- the dataset has no
      explicit pending/settled flag."""
    pat = bundle["pattern"]
    exposure = episode_exposure(bundle["episode"])
    testing = bundle.get("testing") or {}
    ring = bundle.get("ring") or {}
    fraud_linked = bundle.get("fraud_linked_connected_cards") or []
    confirmed_fraud_card_count = len(fraud_linked) + (1 if assessment["verdict"] == "fraud" else 0)
    return dict(
        fraud_probability=assessment["fraud_probability"], exposure_usd=exposure,
        single_signal=assessment["single_signal"], verdict=assessment["verdict"],
        customer_confirmed=customer_confirmed, customer_denied=customer_denied, no_reply_24h=no_reply_24h,
        pending_auth=(trigger_type == "risk_score"),
        purchase_over_100_cleared=bool(testing.get("larger_purchases_after")) and
                                   any(abs(t["amount"]) > 100 for t in bundle["episode"] if t["txn"] in (testing.get("larger_purchases_after") or [])),
        is_card_testing=(pat.pattern == "card_testing"),
        shared_origin=({"kind": "device profile", **ring} if ring.get("n_cards", 0) >= 3 else None),
        disputed_matches_recurring=False,  # see docstring: not detectable from this dataset
        is_undocumented_coordinated=(pat.pattern == "undocumented"),
        evidence_conflicts=bool(pat.alternatives) and pat.confidence <= 0.55,
        confirmed_fraud_card_count=confirmed_fraud_card_count,
        credentials_confirmed_compromised=(customer_denied and pat.pattern == "account_takeover"),
    )
