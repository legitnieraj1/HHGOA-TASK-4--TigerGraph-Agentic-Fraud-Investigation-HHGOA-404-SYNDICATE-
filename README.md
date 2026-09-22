# TigerGraph Agentic Fraud Investigation

An agent that investigates card-fraud alerts on a graph: it pulls a customer's transaction history and
relationships from TigerGraph, runs pattern detectors calibrated against 5,565 real closed cases, retrieves
grounded policy and prior-case context (GraphRAG), decides when it needs more evidence, recommends actions under
an approval-gated policy, and writes the resolved case back into the graph as memory for the next investigation.

Built for the TigerGraph × Hacker House Goa / IEEE Agentic Fraud Investigation challenge.

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                TigerGraph Savanna                   │
                    │  Customer ─OWNS→ Card ─MADE→ Transaction             │
                    │       Transaction ─FROM_DEVICE→ DeviceProfile        │
                    │       Transaction ─BILLED_IN→ BillingRegion          │
                    │       ClosedCase ─INVOLVES→ Transaction              │
                    │       InvestigationCase ─HAS_EVIDENCE/TOOK_ACTION/   │
                    │            SIMILAR_TO→ ...                          │
                    │  + vector search: PolicyDoc.emb, ClosedCase.emb,     │
                    │    InvestigationCase.emb (384-d, cosine, HNSW)       │
                    └───────────────────┬───────────────────────────────--┘
                                        │  tigergraph-mcp (69 tools) /
                                        │  tigergraph/client.py (bulk ops)
                    ┌───────────────────▼───────────────────────────────--┐
                    │              LangGraph agent (agent/)                │
                    │  trigger → investigate → gather_evidence →           │
                    │  assess_uncertainty ⇄ gather_more →                  │
                    │  next_best_action → explain → update_memory          │
                    │                                                      │
                    │  Deterministic: detectors/ (pattern rules + a        │
                    │  calibrated propensity model), agent/policy_engine   │
                    │  (rules R1-R10), agent/uncertainty (stop rule).      │
                    │  LLM (Gemini 3.6 Flash, NVIDIA fallback): explain    │
                    │  node only -- summary/SAR text, never detection.     │
                    └───────────────────┬───────────────────────────────--┘
                                        │
                    ┌───────────────────▼───────────────────────────────--┐
                    │  cases/*.json (20 answer files)  +  api/ + ui/       │
                    └──────────────────────────────────────────────────---┘
```

## Setup

1. **Python 3.11**, then `make venv` (creates `.venv`, installs `pyproject.toml`).
2. **TigerGraph Savanna**: create a workspace at https://savanna.tgcloud.io (auto-suspend/resume on). Get its
   host from the Admin Portal URL's `domain=` param (the Connect dropdown doesn't show it), and a database
   secret from **Database Secrets**.
3. **Dataset**: place the `HHGOA_IEEE` files in `data/raw/` (`README.md`, `case_pack.csv`,
   `closed_cases_history.csv`, `identity.csv`, `transactions.csv`).
4. Copy `.env.example` to `.env` and fill in `TG_HOST`, `TG_GRAPH=FraudGraph`, `TG_SECRET`, and an LLM key
   (`GEMINI_API_KEY` and/or `NVIDIA_API_KEY` -- see `LLM_CHAIN` for the fallback order).
5. `mcp/.env` mirrors the TigerGraph config for `tigergraph-mcp` (see `mcp/README.md`).

## Reproduce everything

```
make up              # profile -> graph schema -> export -> load -> verify -> features -> propensity model -> queries
make mcp-smoke        # confirms the MCP server + LLM can tool-call the graph
.venv/bin/python scripts/40_seed_memory.py          # embed + upsert policy + closed-case vectors
.venv/bin/python scripts/60_run_benchmark.py         # the 20 case_pack cases -> cases/*.json
```

`scripts/50_run_case.py <case_id>` runs one case (accepts an `HHG-###` case_pack id, or a `CC-####` closed-case
id for validation against a known outcome). `scripts/45_memory_eval.py` reproduces the case-memory ablation.

## How TigerGraph is used

- **Graph storage**: the full schema in `tigergraph/spec.py` (single source of truth for the DDL, the DuckDB
  export SQL, and the loading jobs, so they can't drift apart) -- 590,742 transactions, 14,317 cards, 13,553
  customers, 5,565 closed cases, all with real edges, not a flattened table.
- **Vector storage**: TigerGraph's native vector attributes (`emb`, 384-d, cosine, HNSW), not a separate vector
  DB -- `PolicyDoc` (29 chunked policy/typology/regulatory clauses), `ClosedCase` (5,565 case summaries),
  `InvestigationCase` (the agent's own resolved cases, growing case memory).
- **Graph algorithms / pattern detection**: 14 installed GSQL queries (`tigergraph/queries/`) -- evidence
  queries (`card_window`, `card_behaviour`, `customer_profile`, `card_neighbourhood`, `trace_chain`), pattern
  queries with sliding-window logic in GSQL itself (`pattern_card_testing`, `pattern_structuring`,
  `pattern_device_ring`, `device_hubs` for global ring/degree-centrality scans, `region_cluster`,
  `email_neighbors`), and vector search (`vector_search_policy`, `vector_search_cases`).
- **MCP**: the official `tigergraph-mcp` server exposes all of the above (plus generic GSQL/vector/schema tools)
  to any LLM client; `agent/tools/graph_mcp.py` wires it into LangChain/LangGraph.

## Data-derived facts worth knowing (see `NOTES.md` for the full log)

- `card_id` is not a column in the dataset -- it's derived (`customer_id-K{rank of card6, NULLs first}`),
  validated against all 14,955 closed-case transaction links with 0 mismatches.
- `risk_score` is a *reason to look*, not a fraud signal on its own: fraud-vs-cleared AUC is 0.058 (inverted) on
  the closed-case population. A calibrated propensity model trained only on closed-case labels (OOF AUC 0.947)
  is used instead, blended per-pattern with the rule-based pattern confidence (the propensity model is
  "blind" to in-person account-takeover/out-of-region fraud and to undocumented structuring/ring patterns --
  documented and handled, not glossed over).
- Case memory materially changes the assessment: on 1,580 held-out closed cases, accuracy on the
  account-takeover-vs-out-of-region ambiguity goes from 50.9% to 75.3% with same-card case-history memory.

## Repository layout

See `NOTES.md` for the full phase-by-phase decision log (every gotcha, every bug found and fixed, every
prompt.md-vs-README conflict and how it was resolved). `outputs/ANSWER_FORMAT.md` is the README's answer format,
extracted verbatim. `outputs/ACCEPTANCE.md` maps each "what success looks like" point to a concrete artifact.
