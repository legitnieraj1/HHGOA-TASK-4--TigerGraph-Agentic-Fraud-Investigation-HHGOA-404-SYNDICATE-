"""Node 3: gather_evidence. Retrieves the grounded policy/typology/regulatory + case-memory context (GraphRAG)
for the pattern the investigate node found, and folds semantic similar-case retrieval into the evidence list.
Graph pattern-detection itself already happened in investigate (detectors.evidence.build); this node adds the
RAG layer that gives the LLM synthesised, cited context instead of raw rows (spec's core GraphRAG requirement)."""
from graphrag.retrieve import retrieve


def run(state: dict, tg) -> dict:
    bundle = state["evidence_bundle"]
    fa = bundle["flagged_txn"]
    summary = (f"{bundle['channel']} transaction ${fa['amount']:.2f} {fa['product_cd']}, "
              f"risk_score {fa['risk_score']:.2f}, episode of {len(bundle['episode'])} transaction(s)")
    r = retrieve(tg, bundle["pattern"], summary, k_policy=5, k_cases=3)

    evidence = list(state.get("evidence", []))
    semantic_cases = [h["case_id"] for h in r["case_hits"] if h["distance"] < 0.6]
    if semantic_cases:
        evidence.append({"claim": f"GraphRAG semantic retrieval surfaced {len(semantic_cases)} similar prior case(s) "
                                  f"by case narrative (not just same-card history): {', '.join(semantic_cases)}",
                         "source": "graph", "ref": "query:vector_search_cases", "entity_ids": semantic_cases})
    if r["policy_hits"]:
        top = r["policy_hits"][0]
        evidence.append({"claim": f"Retrieved policy/typology guidance: {top['title']} ({top['chunk_id']})",
                         "source": "document", "ref": top["chunk_id"], "entity_ids": []})
    all_similar = sorted(set(bundle.get("similar_prior_cases", [])) | set(semantic_cases))
    return {"retrieval": r, "evidence": evidence, "evidence_bundle": {**bundle, "similar_prior_cases": all_similar}}
