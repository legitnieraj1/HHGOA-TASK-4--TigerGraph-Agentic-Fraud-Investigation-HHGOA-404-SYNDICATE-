"""Writes the resolved investigation back into TigerGraph as case memory (spec: 'write it into the graph so
later investigations can find it'). Creates an InvestigationCase vertex (embedded for future semantic retrieval,
same mechanism as graphrag/retrieve.py's ClosedCase search), Action vertices for every recommended action,
HAS_EVIDENCE / CASE_ON_CARD / CASE_CONNECTED_TO / CASE_DEVICE / TOOK_ACTION / SIMILAR_TO edges."""
from graphrag.embed import embed
from tigergraph.client import TG


def write_case(tg: TG, *, case_id: str, trigger_type: str, status: str, verdict: str, fraud_probability: float,
              pattern: str, exposure_usd: float, opened_at: str, summary: str,
              flagged_txn_id: int, card_id: str, episode_txn_ids: list, connected_card_ids: list,
              device_keys: list, actions: list, similar_prior_case_ids: list) -> str:
    """actions: list of (action_id, action_name, route, phase, reason, status). Returns the graph_case_id
    (== case_id, an InvestigationCase vertex is 1:1 with an answer file's case_id -- HHG-001 etc.)."""
    vec = embed(summary)
    vertices = {
        "InvestigationCase": {case_id: {
            "trigger_type": {"value": trigger_type}, "status": {"value": status}, "verdict": {"value": verdict},
            "pattern": {"value": pattern}, "fraud_probability": {"value": fraud_probability},
            "exposure_usd": {"value": exposure_usd}, "opened_at": {"value": opened_at},
            "summary": {"value": summary}, "answer_json": {"value": ""}, "emb": {"value": vec},
        }},
        "Action": {a[0]: {"action": {"value": a[1]}, "route": {"value": a[2]}, "phase": {"value": a[3]},
                          "reason": {"value": a[4]}, "status": {"value": a[5]}} for a in actions},
    }
    edges = {"InvestigationCase": {case_id: {
        "HAS_EVIDENCE": {"Transaction": {str(t): {"claim": {"value": ""}} for t in set(episode_txn_ids) | {flagged_txn_id}}},
        "CASE_ON_CARD": {"Card": {card_id: {}}},
        "TOOK_ACTION": {"Action": {a[0]: {} for a in actions}},
    }}}
    if connected_card_ids:
        edges["InvestigationCase"][case_id]["CASE_CONNECTED_TO"] = {"Card": {c: {} for c in connected_card_ids}}
    if device_keys:
        edges["InvestigationCase"][case_id]["CASE_DEVICE"] = {"DeviceProfile": {d: {} for d in device_keys if d}}
    if similar_prior_case_ids:
        edges["InvestigationCase"][case_id]["SIMILAR_TO"] = {"ClosedCase": {c: {"score": {"value": 1.0}} for c in similar_prior_case_ids}}

    r = tg.upsert({"vertices": vertices, "edges": edges})
    if r.get("error"):
        raise RuntimeError(f"memory write failed for {case_id}: {r.get('message')}")
    return case_id
