"""Node 1: trigger. Accepts a fraud signal (case_pack row) or an ad-hoc request, opens the case. No graph write
here -- the graph write happens once, in update_memory, with the FULL resolved case (a documented simplification;
see NOTES.md Phase 5)."""
import time


def run(state: dict) -> dict:
    return {
        "round_no": 0, "evidence": [], "evidence_requests": [], "evidence_request_outcome": None,
        "customer_confirmed": False, "customer_denied": False, "no_reply_24h": False,
        "t_start": time.time(), "tool_calls_start": state.get("tool_calls_start", 0),
    }
