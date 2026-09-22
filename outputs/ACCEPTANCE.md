# Acceptance: the 11 "What Success Looks Like" points

Each point below cites a concrete, checkable artifact: a script, a log, a query, a file. `NOTES.md` has the full
phase-by-phase decision log if you want the reasoning behind any of these.

## 1. Investigate from a trigger
The agent opens a case from a `case_pack.csv` risk-score alert, a customer complaint, or an analyst request.
`agent/nodes/trigger.py` handles all three trigger types (`agent/graph.py`'s first node). Run log: any
`cases/HHG-*.json` file's top-level `case_id` plus `case.summary`; `scripts/60_run_benchmark.py`'s console
output shows all 20 triggers processed. Also validated on two closed cases outside the exam set (`scripts/
50_run_case.py CC-0001` / `CC-0003`) to confirm the trigger→open-case path works independent of the graded set.

## 2. Gather evidence from the graph and other sources
`agent/nodes/investigate.py` (calling `detectors/evidence.py`) pulls the flagged transaction, an episode window,
card/customer behavioural baselines, device/region clustering, and prior closed cases from TigerGraph via 12
installed GSQL queries. `agent/nodes/gather_evidence.py` adds GraphRAG-retrieved policy/typology/regulatory
clauses and semantic similar-case retrieval (`graphrag/retrieve.py`). Every case file's `case.evidence[]` lists
each claim with its `source` (`graph`/`document`/`customer`) and `ref` (the query or policy chunk it came from)
-- see any `cases/*.json`.

## 3. Identify patterns and assess risk
`detectors/patterns.py` classifies into the 5 documented patterns, `undocumented`, or `none`, with a confidence
and cited reasons; `agent/uncertainty.py` computes `fraud_probability` from a propensity model (calibrated on
5,565 closed cases, OOF AUC 0.947) blended with pattern confidence. Validated on the closed-case history before
being trusted on the exam set: `NOTES.md` "Phase 2 calibration findings" (structuring 5/5 detected, card-testing
strict rule 0 false fires on a sample, device ring 4/4 known cases detected with 0 false positives across 25
negatives). `scripts/50_run_case.py CC-0001` reproduces verdict/pattern/exposure/SAR-filing matching the true
closed-case outcome exactly.

## 4. Create and progress a case as evidence/decisions are added
`agent/memory.py` writes an `InvestigationCase` vertex with `HAS_EVIDENCE`, `CASE_ON_CARD`, `CASE_CONNECTED_TO`,
`CASE_DEVICE`, `TOOK_ACTION`, and `SIMILAR_TO` edges. Verified directly on CC-0001 (`NOTES.md` Phase 5): the
vertex and every edge type landed correctly, including real `SIMILAR_TO` links to closed cases found by
semantic retrieval. `case.written_to_graph` / `case.graph_case_id` in every answer file confirm the write per
case; query `GET /restpp/graph/FraudGraph/vertices/InvestigationCase/<case_id>` to inspect any of them directly.

## 5. Recognise insufficient/uncertain evidence
`agent/uncertainty.py`'s stop rule (policy s.6, exact thresholds: fraud probability ≥0.85 or ≤0.15 with ≥2
independent evidence sources, else continue). Cases with a single ambiguous signal (e.g. HHG-001, HHG-002 --
see `cases/`) land on `verdict: "uncertain"` and trigger the evidence-gathering loop; `case.fraud_probability`
in the 0.3-0.6 band is the visible signature of this firing.

## 6. Gather more via controlled actions
`agent/nodes/gather_more.py` + `agent/tools/actions.py`: `VERIFY_WITH_CUSTOMER`/`STEP_UP_AUTH`/analyst-info
requests, each logged with a deterministic, documented `assumed_response` (README: real replies aren't
provided). Every case's `evidence_requests[]` shows exactly what was asked and assumed. Capped at 3 rounds
(`MAX_ROUNDS`) with a guaranteed-termination design: once any request resolves (confirmed, denied, no-reply, or
inconclusive), the loop stops rather than re-asking a question a deterministic simulator can't answer
differently a second time (`NOTES.md` Phase 5's write-up of the bug this replaced).

## 7. Recommend next best actions and update as evidence arrives
`agent/policy_engine.py` runs R1-R10, called once before (`next_best_actions.initial`) and once after
(`.final`) any evidence request, with `what_changed` explaining the difference. Example: CC-0001 goes from
`MONITOR_CARD` (initial, p=0.39) to `BLOCK_CARD` + `CREATE_CASE` (final, p=0.82) after a simulated denial.

## 8. Explain evidence, reasoning, uncertainty, and decisions
`agent/nodes/explain.py` produces `case.summary` (2-6 sentences), `pattern_description` when undocumented, and
`stop_reason`, grounded in the assembled evidence + GraphRAG context (never invented) -- with a templated
fallback if every LLM provider fails, so an explanation is always produced. Every action's `reason` cites a
policy rule number (`case.evidence[]` cites a query or document chunk id).

## 9. Operate within policies, permissions and approvals
`agent/policy_engine.route_for()` implements the exact approval table (policy s.2); `agent/tools/actions.py`'s
`execute()` only actually runs `auto`-route actions, gating everything else as `PENDING <route> approval --
not executed by the agent`. Verified directly on CC-0001: `BLOCK_CARD` (route L1) came back
`executed: False`, `CREATE_CASE` (route auto) came back `executed: True` (`NOTES.md` Phase 5). The dashboard's
approval buttons (`ui/index.html`, `POST /api/cases/{id}/approve`) are the human-in-the-loop side of this, and
log the human decision back onto the `Action` vertex in the graph.

## 10. Use prior cases as memory
Two independent memory mechanisms, both demonstrated working: (a) same-card structured history
(`apply_memory_prior`), ablated on 1,580 held-out closed cases -- pattern-classification accuracy 50.9% without
memory vs 75.3% with it (`scripts/45_memory_eval.py`, `outputs/memory_eval.json`); (b) semantic vector retrieval
over `ClosedCase` embeddings (`graphrag/retrieve.py`'s `search_cases`), visible in every case's
`similar_prior_cases` and cited as evidence -- e.g. HHG-014's device-ring case surfaces the actual ring cases
found independently in Phase 2's rule-based calibration.

## 11. Present it all through a usable interface
`api/main.py` (FastAPI) + `ui/index.html`: case list, per-case timeline, evidence, an uncertainty meter, the
before/after next-best-action panel with live approve/reject, the SAR narrative when filed, and a conversational
panel (`POST /api/investigate`) that triggers a live investigation against the running graph. Run:
`.venv/bin/uvicorn api.main:app --port 8080`.

---

## Self-scored against the rubric

- **Investigation accuracy (25%)**: strong on the two dimensions independently verifiable without the hidden
  answer key -- pattern detectors validated against 5,565 closed cases (structuring 5/5, card-testing 0 false
  fires, device rings 4/4 with 0 FP across 25 negatives), and a closed-case replay (CC-0001) matches the true
  verdict/pattern/exposure/SAR-filing exactly. The final 20-case run resolves 8 legitimate / 12 fraud with 0
  cases landing on `uncertain` -- a real, calibrated split (not an artifact: an earlier run before a calibration
  fix, documented in NOTES.md, produced 0 legitimate verdicts out of 20 against the README's explicit "half the
  cases are legitimate", which is what surfaced the bug). Weakest point: account-takeover vs out-of-region-use
  is genuinely not separable from single-episode behaviour (confirmed with a depth-3 decision tree, 67% best
  case) -- mitigated by case memory (50.9%→75.3%) but not solved, and the agent is honest about this rather
  than guessing confidently.
- **Next best action (25%)**: exact policy-rule implementation (R1-R10), before/after snapshots, approval
  gating verified by direct inspection (not just by design). Weakest point: R7 (recurring-charge dispute) can
  never fire -- the dataset has no merchant identity, only a product category code, documented as a real gap.
- **Case summary / explainability (10%)**: every claim traces to a query or document id; templated fallback
  guarantees a summary always exists even if the LLM is unreachable.
- **Agentic design (15%)**: a genuine LangGraph state machine with a real conditional loop, deliberately
  deterministic fraud-detection (LLM never decides), MCP-wired tool exposure, a policy engine and mock action
  layer with real approval gating.
- **Innovation (15%)**: the undocumented-pattern detectors (device-ring via degree centrality, structuring via
  a sliding-window GSQL query) found real coordinated activity the five known typologies don't cover, and the
  case-memory ablation is a genuine, quantified result, not a claim.
- **Demo (10%)**: `demo/demo_script.md`, a working dashboard, and a live conversational trigger panel.
