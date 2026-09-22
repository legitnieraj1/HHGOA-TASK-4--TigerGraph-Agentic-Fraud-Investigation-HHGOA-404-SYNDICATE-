"""Rule layer that turns graph evidence bundles into a pattern label + strength. Deterministic; the LLM never decides this.

Thresholds are calibrated on the closed cases (see NOTES.md, Phase 2). Every rule returns the evidence that fired so the
explanation can cite it. Bundles come from the installed GSQL queries (pattern_* / card_window / pattern_device_ring)."""
from dataclasses import dataclass, field
from typing import Optional

# ---- calibrated constants (NOTES.md "Phase 2 calibration findings") ----
EPISODE_HOURS = 24          # +-24h same-card window for episode reconstruction (F1 0.885)
EPISODE_P_MIN = 0.5         # propensity threshold to join the episode
TESTING_TINY_AMT = 5.0      # tiny online auth
TESTING_LARGE_AMT = 10.0
TESTING_WINDOW_H = 168      # +-168h: loose recall 10/16, 0 false fires on sample
STRUCT_THRESHOLDS = (250.0, 500.0, 1000.0, 2000.0)
STRUCT_MINUTES = 60
STRUCT_HOURS = 6
RING_MIN_CARDS = 5
RING_MIN_SHARE_NEW = 0.9    # ring device is `New` on ~every account it touches
RING_MIN_SHARE_PROXY = 0.8  # ...behind a proxy (anonymous in the observed ring)

PATTERNS = ("card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use",
            "account_takeover", "undocumented", "none")


@dataclass
class PatternResult:
    pattern: str
    confidence: float                       # strength of this LABEL (not fraud probability)
    description: str = ""                   # required text when pattern == "undocumented"
    reasons: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)   # (pattern, confidence) the evidence also fits
    flags: dict = field(default_factory=dict)


def ring_strength(ring: dict) -> Optional[dict]:
    """ring = flattened pattern_device_ring output. Returns strength dict or None if it is not ring-like.
    Ring-ness = the device is New + proxied across (nearly) all of its activity, on several distinct cards.
    A popular generic device (Windows/Chrome, iPhone) also has many cards but mixed status, so it does not qualify."""
    n_txns = ring.get("n_txns") or 0
    n_cards = ring.get("n_cards") or 0
    if n_txns == 0 or n_cards < RING_MIN_CARDS:
        return None
    share_new = (ring.get("dev_status_counts") or {}).get("New", 0) / n_txns
    proxy = ring.get("proxy_counts") or {}
    share_proxy = sum(v for k, v in proxy.items() if k) / n_txns
    share_anon = proxy.get("IP_PROXY:ANONYMOUS", 0) / n_txns
    if share_new < RING_MIN_SHARE_NEW or share_proxy < RING_MIN_SHARE_PROXY:
        return None
    fraud_cards = len(ring.get("fraud_linked_cards") or [])
    conf = 0.6 + 0.1 * min(fraud_cards, 3) + (0.1 if share_anon >= 0.9 else 0.0)
    return {"n_cards": n_cards, "n_txns": n_txns, "share_new": round(share_new, 3), "share_proxy": round(share_proxy, 3),
            "share_anonymous_proxy": round(share_anon, 3), "fraud_linked_cards": fraud_cards, "confidence": round(min(conf, 0.95), 2)}


def classify(episode: list, structuring: Optional[dict] = None, testing: Optional[dict] = None,
             ring: Optional[dict] = None) -> PatternResult:
    """episode: list of dicts with channel, dev_status, product, addr1 (episode txns incl. the flagged one).
    structuring/testing/ring: bundles from the GSQL pattern queries (may be None)."""
    if not episode:
        return PatternResult("none", 0.9, reasons=["no suspicious episode reconstructed"])
    n = len(episode)
    online = [t for t in episode if t.get("channel") == "online"]
    inperson = [t for t in episode if t.get("channel") == "in_person"]
    any_new = any(t.get("dev_status") == "New" for t in episode)
    n_prod = len({t.get("product") for t in episode})
    n_addr = len({t.get("addr1") for t in episode if t.get("addr1", -1) not in (None, -1)})
    flags = {"n": n, "n_online": len(online), "n_inperson": len(inperson), "any_new_device": any_new,
             "n_products": n_prod, "n_regions": n_addr}
    alts = []

    # 1) undocumented: structuring under a limit
    if structuring and structuring.get("match"):
        T = structuring["threshold"]
        return PatternResult(
            "undocumented", 0.85,
            description=(f"Structuring: {structuring['max_in_window']} online purchases within {STRUCT_MINUTES} minutes, each just under "
                         f"${T:,.0f} (total ${structuring['run_total']:,.2f}), amounts kept below an authorization threshold. Found by scanning the "
                         f"card's online purchases in the surrounding window; it matches none of the five documented typologies."),
            reasons=[f"{structuring['max_in_window']} online purchases in [{0.8*T:,.0f}, {T:,.0f}) inside {STRUCT_MINUTES} min"], flags=flags)
    # 2) undocumented: shared-device ring
    rs = ring_strength(ring) if ring else None
    if rs:
        return PatternResult(
            "undocumented", rs["confidence"],
            description=(f"Coordinated shared-device ring: one device profile appears as New behind a proxy on {rs['n_cards']} distinct cards "
                         f"({rs['n_txns']} transactions), {rs['fraud_linked_cards']} of them already tied to confirmed-fraud cases. "
                         f"Found by device-centrality over the card-device graph, not by any single card's behaviour."),
            reasons=[f"device New on {rs['share_new']:.0%} and proxied on {rs['share_proxy']:.0%} of its activity across {rs['n_cards']} cards"],
            flags={**flags, "ring": rs})
    # 3) card testing
    if testing and testing.get("strict_match"):
        return PatternResult("card_testing", 0.9, reasons=[f"{testing['max_tiny_in_60min']} tiny online auths within 60 min, then a larger purchase"], flags=flags)
    if testing and testing.get("loose_match") and len(online) == n:
        alts.append(("card_testing", 0.55))
    # 4) channel composition (labels in the closed history follow it exactly for online episodes)
    if len(online) == n:
        if any_new:
            return PatternResult("card_not_present_new_device", 0.85, reasons=["all transactions online; device marked New for the account"], alternatives=alts, flags=flags)
        if alts:
            return PatternResult("card_testing", 0.55, reasons=["tiny online authorisations before a larger purchase (loose match)"],
                                 alternatives=[("card_not_present_fraud", 0.4)], flags=flags)
        return PatternResult("card_not_present_fraud", 0.85, reasons=["all transactions online; device not flagged New"], flags=flags)
    if online and inperson:
        return PatternResult("account_takeover", 0.6, reasons=["mixed online and in-person activity inconsistent with one cardholder"],
                             alternatives=[("out_of_region_use", 0.3)], flags=flags)
    # in-person only: ATO vs OOR not separable in the history (67% best case); report as a soft call
    if n_prod > 1 or n_addr > 1 or n >= 4:
        return PatternResult("account_takeover", 0.5, reasons=["in-person only but several products/regions/transactions"],
                             alternatives=[("out_of_region_use", 0.45)], flags=flags)
    return PatternResult("out_of_region_use", 0.5, reasons=["in-person only, single product and region"],
                         alternatives=[("account_takeover", 0.4)], flags=flags)


def apply_memory_prior(result: PatternResult, prior_closed_patterns: list) -> PatternResult:
    """Nudge an ATO/OOR call using case memory: the most recent CONFIRMED-FRAUD pattern on the same card/customer.
    Calibration (NOTES.md): among in-person-only ATO/OOR cases with a prior fraud case on the same card (1,580/2,160),
    the prior case's pattern matches the new one 65% of the time -- a real but noisy signal, applied only as a tiebreak
    between the two patterns the composition rule already can't separate (never overrides card_testing/CNP/undocumented,
    which the composition rule gets right ~100% of the time)."""
    if result.pattern not in ("account_takeover", "out_of_region_use") or not prior_closed_patterns:
        return result
    prior = prior_closed_patterns[0]  # caller passes most-recent-first
    if prior not in ("account_takeover", "out_of_region_use") or prior == result.pattern:
        return result
    # prior disagrees with the rule call: 65% of the time memory is right, so swap but keep confidence modest
    other_conf = next((c for p, c in result.alternatives if p == prior), 0.4)
    swapped = PatternResult(prior, round(min(0.65, other_conf + 0.15), 2),
                            reasons=result.reasons + [f"case memory: most recent confirmed-fraud case on this card was '{prior}' (CC history, 65% same-pattern rate)"],
                            alternatives=[(result.pattern, result.confidence)] + [a for a in result.alternatives if a[0] != prior],
                            flags=result.flags)
    return swapped
