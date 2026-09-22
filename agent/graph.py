"""The LangGraph state machine (spec: "the investigation is an explicit state machine ... with conditional
loops, which is exactly what LangGraph is for"):

  trigger -> investigate -> gather_evidence -> assess_uncertainty --[uncertain, round < cap]--> gather_more -+
                                                       ^-------------------------------------------------------+
                                                       |
                                              [stop: confident or round cap]
                                                       v
                                          next_best_action -> explain -> update_memory -> END

`tg` (a live tigergraph.client.TG) is bound into the graph nodes that need it via closures at build time --
it's a shared client, not part of the serializable case state."""
from langgraph.graph import StateGraph, START, END

from agent.state import CaseState
from agent.nodes import trigger, investigate, gather_evidence, assess_uncertainty, gather_more, next_best_action, explain, update_memory


def _route_after_assess(state: CaseState) -> str:
    return "next_best_action" if state["assessment"]["should_stop"] else "gather_more"


def build_graph(tg):
    g = StateGraph(CaseState)
    g.add_node("trigger", trigger.run)
    g.add_node("investigate", lambda s: investigate.run(s, tg))
    g.add_node("gather_evidence", lambda s: gather_evidence.run(s, tg))
    g.add_node("assess_uncertainty", assess_uncertainty.run)
    g.add_node("gather_more", gather_more.run)
    g.add_node("next_best_action", next_best_action.run)
    g.add_node("explain", explain.run)
    g.add_node("update_memory", lambda s: update_memory.run(s, tg))

    g.add_edge(START, "trigger")
    g.add_edge("trigger", "investigate")
    g.add_edge("investigate", "gather_evidence")
    g.add_edge("gather_evidence", "assess_uncertainty")
    g.add_conditional_edges("assess_uncertainty", _route_after_assess, {"gather_more": "gather_more", "next_best_action": "next_best_action"})
    g.add_edge("gather_more", "assess_uncertainty")
    g.add_edge("next_best_action", "explain")
    g.add_edge("explain", "update_memory")
    g.add_edge("update_memory", END)
    return g.compile()


def run_case(tg, *, case_id, trigger_type, trigger_text, opened_at, flagged_txn_id, card_id, customer_id,
            risk_score_input=None) -> CaseState:
    """Runs one case end to end. Recursion limit generous but finite: the gather_more<->assess_uncertainty loop
    is itself capped at MAX_ROUNDS (agent/uncertainty.py), so this is just headroom, not the real termination guard."""
    app = build_graph(tg)
    initial: CaseState = {
        "case_id": case_id, "trigger_type": trigger_type, "trigger_text": trigger_text, "opened_at": opened_at,
        "flagged_txn_id": flagged_txn_id, "card_id": card_id, "customer_id": customer_id,
        "risk_score_input": risk_score_input, "tool_calls_start": tg.calls,
    }
    return app.invoke(initial, config={"recursion_limit": 25})
