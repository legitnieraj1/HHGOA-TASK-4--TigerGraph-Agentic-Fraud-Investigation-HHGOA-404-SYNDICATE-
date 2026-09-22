"""Node 2: investigate. Pulls entities, transactions, relationships, behaviour, and similar prior cases (memory)
via detectors.evidence.build() -- graph facts only, no LLM. This IS the bulk of "gather evidence from the graph"
too (spec's investigate/gather_evidence split is conceptual; build() does both in one set of graph calls to
avoid re-fetching the same baselines twice)."""
from detectors.evidence import build


def run(state: dict, tg) -> dict:
    bundle = build(tg, state["flagged_txn_id"], state["card_id"], state["customer_id"])
    return {"evidence_bundle": bundle, "evidence": list(bundle["evidence"])}
