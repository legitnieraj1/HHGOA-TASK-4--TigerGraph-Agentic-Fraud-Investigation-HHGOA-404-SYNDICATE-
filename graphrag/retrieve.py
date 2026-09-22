"""GraphRAG retrieval: embed a query, search PolicyDoc / ClosedCase vectors via the installed vectorSearch
queries, and synthesise a grounded context block (cite the clause + the fact) for the LLM. Never passes raw
CSV rows or full documents -- every string here is either a policy chunk (graphrag/chunk.py) or a short,
derived case summary.

NOTE: `vectorSearch`'s PRINTed vertex order is NOT sorted by distance (verified empirically, NOTES.md Phase 4)
-- always sort by the returned distance_map yourself. COSINE distance: lower = closer."""
from tigergraph.client import TG
from graphrag.embed import embed


def _attr(row, key):
    """PRINT with column aliases (SYNTAX v3) prefixes attribute keys with the source variable, e.g. 'v.chunk_id'."""
    a = row["attributes"]
    return a.get(key) if key in a else a.get(f"v.{key}")


def search_policy(tg: TG, query_text: str, k: int = 5):
    """Returns [{chunk_id, source, section, title, text, distance}], sorted closest-first."""
    q = embed(query_text)
    r = tg.run_query("vector_search_policy", query_vector=q, k=k)
    if r.get("error"):
        raise RuntimeError(r.get("message"))
    o = {}
    for d in r["results"]:
        o.update(d)
    dist = o.get("distances", {})
    out = [{"chunk_id": _attr(row, "chunk_id"), "source": _attr(row, "source"), "section": _attr(row, "section"),
            "title": _attr(row, "title"), "text": _attr(row, "text"), "distance": dist.get(row["v_id"], 1.0)}
           for row in o.get("v", [])]
    return sorted(out, key=lambda x: x["distance"])


def search_cases(tg: TG, query_text: str, k: int = 5):
    """Returns [{case_id, customer_id, card_id, outcome, pattern, exposure_usd, analyst_notes, distance}], sorted closest-first."""
    q = embed(query_text)
    r = tg.run_query("vector_search_cases", query_vector=q, k=k)
    if r.get("error"):
        raise RuntimeError(r.get("message"))
    o = {}
    for d in r["results"]:
        o.update(d)
    dist = o.get("distances", {})
    out = [{"case_id": _attr(row, "case_id"), "customer_id": _attr(row, "customer_id"), "card_id": _attr(row, "card_id"),
            "outcome": _attr(row, "outcome"), "pattern": _attr(row, "pattern"), "exposure_usd": _attr(row, "exposure_usd"),
            "analyst_notes": _attr(row, "analyst_notes"), "distance": dist.get(row["v_id"], 1.0)}
           for row in o.get("v", [])]
    return sorted(out, key=lambda x: x["distance"])


def query_text_for(pattern_result, flagged_txn_summary: str) -> str:
    """Builds the retrieval query from a case's suspected pattern + entities, per the spec ("given a case's
    entities + suspected pattern, retrieve..."). Keep it descriptive, not just the pattern name -- semantic
    search does better on a sentence than a label."""
    p = pattern_result
    bits = [flagged_txn_summary, f"suspected pattern: {p.pattern}"] + list(p.reasons)
    if p.description:
        bits.append(p.description)
    return ". ".join(bits)


def synthesize_context(policy_hits, case_hits, max_policy=4, max_cases=3) -> str:
    """A single grounded text block for the LLM: cited policy/typology/regulatory clauses + cited prior cases.
    Never raw rows -- policy hits are already-chunked text, case hits are the analyst's own closed-case summary."""
    lines = ["## Relevant policy, typology and regulatory clauses (cite by id in parentheses):"]
    for h in policy_hits[:max_policy]:
        lines.append(f"- ({h['chunk_id']}) {h['title']}: {h['text']}")
    if case_hits:
        lines.append("\n## Similar prior closed cases (case memory; cite by case_id):")
        for h in case_hits[:max_cases]:
            lines.append(f"- ({h['case_id']}) {h['outcome']}/{h['pattern']}, exposure ${h['exposure_usd']:,.2f}: {h['analyst_notes']}")
    return "\n".join(lines)


def retrieve(tg: TG, pattern_result, flagged_txn_summary: str, k_policy: int = 5, k_cases: int = 3):
    """One-shot: query -> policy hits + case hits -> synthesized context block. This is what gather_evidence
    hands to the LLM alongside the graph evidence bundle (detectors/evidence.py)."""
    qtext = query_text_for(pattern_result, flagged_txn_summary)
    policy_hits = search_policy(tg, qtext, k=k_policy)
    case_hits = search_cases(tg, qtext, k=k_cases)
    return {"query_text": qtext, "policy_hits": policy_hits, "case_hits": case_hits,
            "context": synthesize_context(policy_hits, case_hits)}
