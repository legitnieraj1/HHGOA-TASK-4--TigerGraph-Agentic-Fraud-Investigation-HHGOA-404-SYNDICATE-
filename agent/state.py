"""LangGraph state schema: the shared Case object every node reads/writes. A TypedDict with `total=False` --
nodes return partial updates, LangGraph merges them (default last-write-wins reducer; no field here needs a
custom reducer since each is only ever written by one or two nodes in sequence)."""
from typing import TypedDict


class CaseState(TypedDict, total=False):
    # --- trigger ---
    case_id: str
    trigger_type: str          # risk_score | customer_report | analyst_request
    trigger_text: str
    opened_at: str
    flagged_txn_id: int
    card_id: str
    customer_id: str
    risk_score_input: float | None   # the bank's risk score on the flagged txn, if the trigger carried one

    # --- investigate / gather_evidence ---
    evidence_bundle: dict       # detectors.evidence.build() output (episode, testing/structuring/ring, baselines, pattern)
    retrieval: dict             # graphrag.retrieve.retrieve() output (policy hits, case hits, synthesized context)
    evidence: list              # answer-format case.evidence[] entries, accumulated across rounds

    # --- assess_uncertainty / gather_more loop ---
    round_no: int
    assessment: dict            # agent.uncertainty.Assessment as a dict
    evidence_requests: list     # answer-format evidence_requests[]
    evidence_request_outcome: str | None   # None | confirmed | denied | no_reply | inconclusive (agent/uncertainty.py)
    customer_confirmed: bool
    customer_denied: bool
    no_reply_24h: bool

    # --- next_best_action (recorded twice: before/after evidence_requests) ---
    nba_initial: list           # list of {action, route, reason}
    nba_final: list
    what_changed: str
    exposure_usd: float
    executed_log: list          # ExecutedAction results, for the demo/UI, not part of the answer format itself

    # --- explain ---
    summary: str
    pattern_description: str
    stop_reason: str

    # --- sar ---
    sar: dict

    # --- update_memory ---
    written_to_graph: bool
    graph_case_id: str

    # --- bookkeeping (answer format top level) ---
    tool_calls_start: int        # tg.calls at case start, so tool_calls = tg.calls - this at the end
    tool_calls: int
    tokens: int
    t_start: float
    latency_s: float
