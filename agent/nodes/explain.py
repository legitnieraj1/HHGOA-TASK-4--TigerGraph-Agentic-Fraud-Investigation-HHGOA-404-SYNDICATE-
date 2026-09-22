"""Node 7: explain. Produces the case summary, the pattern_description (when undocumented), and the SAR
narrative when FILE_REPORT is in the final actions -- the one place the LLM's text generation is used, always
over the already-assembled, deterministic evidence + GraphRAG context (never in place of it). Falls back to a
templated summary if every LLM provider fails, so the benchmark can always be produced (NOTES.md: "the
explanation has a templated fallback if the LLM is unreachable")."""
import json

from llm.client import generate, LLMError


def _template_summary(state: dict) -> str:
    bundle = state["evidence_bundle"]
    pat = bundle["pattern"]
    a = state["assessment"]
    return (f"{pat.pattern.replace('_', ' ').title()} on card {state['card_id']}, {len(bundle['episode'])} "
           f"transaction(s), exposure ${state.get('exposure_usd', 0):,.2f}. Fraud probability {a['fraud_probability']:.2f} "
           f"({a['verdict']}). {'; '.join(pat.reasons)}.")


def run(state: dict) -> dict:
    bundle = state["evidence_bundle"]
    pat = bundle["pattern"]
    a = state["assessment"]
    needs_sar = any(x["action"] == "FILE_REPORT" for x in state["nba_final"])

    context = state["retrieval"]["context"]
    prompt = (
        f"You are writing an internal fraud-case summary and (if needed) a SAR narrative. Ground every claim in "
        f"the evidence below; do not invent facts.\n\n"
        f"Case {state['case_id']}, trigger: {state['trigger_type']} -- {state['trigger_text']}\n"
        f"Pattern: {pat.pattern} (confidence {pat.confidence:.2f}). Reasons: {'; '.join(pat.reasons)}\n"
        f"Verdict: {a['verdict']}, fraud probability {a['fraud_probability']:.2f}\n"
        f"Episode: {len(bundle['episode'])} transaction(s), exposure ${state.get('exposure_usd', 0):,.2f}\n"
        f"Evidence gathered: {json.dumps(state['evidence'][:8], default=str)[:2500]}\n"
        f"{context[:2500]}\n\n"
        f"Return ONLY a JSON object with keys:\n"
        f'  "summary": 2-6 sentences an analyst could read (no more).\n'
        f'  "pattern_description": {"required, 2-3 sentences on what the undocumented pattern is, who it affects, how you found it" if pat.pattern == "undocumented" else "empty string"}\n'
        f'  "stop_reason": one sentence, why the investigation ended here.\n'
        + ('  "sar_narrative": 6-12 sentences, who/what/when/where/how/why, standing on its own for a regulator.\n'
           if needs_sar else '  "sar_narrative": ""\n')
    )
    tokens = 0
    try:
        r = generate([{"role": "user", "content": prompt}], response_format={"type": "json_object"}, max_tokens=1200)
        tokens = r.tokens
        j = json.loads(r.text)
        summary = j.get("summary") or _template_summary(state)
        pattern_description = j.get("pattern_description", "") if pat.pattern == "undocumented" else ""
        stop_reason = j.get("stop_reason") or state["assessment"]["stop_reason"]
        sar_narrative = j.get("sar_narrative", "") if needs_sar else ""
    except (LLMError, json.JSONDecodeError, Exception):  # noqa: BLE001 -- never let explanation text block the pipeline
        summary = _template_summary(state)
        pattern_description = pat.description if pat.pattern == "undocumented" else ""
        stop_reason = state["assessment"]["stop_reason"]
        sar_narrative = (f"On {bundle['flagged_txn']['ts'][:10]}, card {state['card_id']} (customer {state['customer_id']}) "
                         f"showed {pat.pattern} activity: {'; '.join(pat.reasons)}. Exposure ${state.get('exposure_usd', 0):,.2f}."
                         if needs_sar else "")

    return {"summary": summary, "pattern_description": pattern_description, "stop_reason": stop_reason,
           "tokens": tokens, "sar": _build_sar(state, needs_sar, sar_narrative)}


def _build_sar(state: dict, file: bool, narrative: str) -> dict:
    bundle = state["evidence_bundle"]
    if not file:
        return {"file": False, "reason": _sar_no_reason(state), "narrative": "", "subjects": [], "total_amount_usd": 0, "activity_dates": []}
    dates = sorted({t["ts"][:10] for t in bundle["episode"]})
    subjects = sorted({state["customer_id"], state["card_id"], *bundle.get("fraud_linked_connected_cards", [])})
    reason_rec = next((x["reason"] for x in state["nba_final"] if x["action"] == "FILE_REPORT"), "policy rule")
    return {"file": True, "reason": reason_rec, "narrative": narrative, "subjects": subjects,
           "total_amount_usd": state.get("exposure_usd", 0), "activity_dates": [dates[0], dates[-1]] if dates else []}


def _sar_no_reason(state: dict) -> str:
    a = state["assessment"]
    if a["verdict"] == "legitimate":
        return "R3/policy: activity confirmed legitimate or fraud probability too low to warrant a filing"
    return "Fraud not confirmed/strongly suspected, or none of policy s.3a's filing conditions (exposure > $1,000, shared origin, coordinated/undocumented) are met"
