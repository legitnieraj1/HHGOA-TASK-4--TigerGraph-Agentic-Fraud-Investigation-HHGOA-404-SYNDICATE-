# Demo script (3-5 minutes)

Goal: show a full investigation, the uncertainty loop firing, a gated approval, a SAR filing, and case memory,
without touching the terminal.

## 0. Before you start
- Workspace awake (Savanna auto-resumes on traffic, but the first request after idle takes ~20s -- open the
  dashboard a few seconds before you're on).
- Have `cases/HHG-014.json` and `cases/CC-0001.json` (or your latest dev run) open in a second tab as a fallback
  if the live demo hits a network hiccup.

## 1. Open with the problem (20s)
"Half of these alerts are legitimate. A model that blocks everything scores badly, and a bank that never blocks
anything eats the fraud. The agent's job is to know which is which, gather more evidence when it doesn't know,
and only act within what it's actually allowed to do."

## 2. Trigger an uncertain case live (60s)
Pick a risk-score case with a single, ambiguous signal (HHG-001 or HHG-012 -- both land near the 0.5 line).
- Open the case in the dashboard. Point at the **evidence subgraph**: the flagged transaction, its card, the
  customer's other cards, the device profile.
- Point at the **uncertainty meter**: this is not the bank's risk score (say so explicitly -- "risk_score is a
  reason to look, never a verdict," and on this dataset it's actually *inverted* on the closed-case population:
  0.058 AUC fraud-vs-cleared. The number driving the meter is a propensity model calibrated on 5,565 real closed
  cases, blended with graph pattern-detection").
- Show it decide it doesn't have enough (single signal, probability not extreme) and fire an evidence request --
  step-up authentication or a customer validation, picked based on what kind of case it is.

## 3. The evidence loop resolves it (45s)
- Show the simulated response landing (this dataset doesn't provide real customer replies, so the response is
  a documented, deterministic function of the agent's own evidence -- point at `evidence_requests[].assumed_response`
  in the case file so it's clear this isn't hidden).
- Show the **NBA before/after**: point at how the recommendation changed -- probability moved, a new action got
  added, an old one dropped. This is `next_best_actions.initial` vs `.final` in the answer file, live in the UI.

## 4. A gated approval (30s)
- Point at a `BLOCK_CARD` or `FILE_REPORT` recommendation sitting in the UI with an **L1/L2** badge -- not
  executed, waiting on a human. Click **Approve**.
- Say plainly: "the agent recommends. Only `auto`-route actions execute themselves. Everything above $2,500 in
  exposure, every SAR filing, blocking every card someone owns -- a person clicks yes."

## 5. A SAR filing (30s)
Switch to a case with `sar.file: true` (HHG-006 or HHG-008 are good: undocumented structuring, card testing).
Show the narrative -- point out it follows FinCEN's own five-W-plus-how structure (grounded in the real SAR
Narrative Guidance document, not invented), and that every fact in it traces back to a graph query or a
retrieved policy clause, visible in the evidence list right above it.

## 6. Case memory (30s)
Open the case's **similar prior cases** panel. Say: "these aren't keyword matches -- they're semantic vector
search over 5,565 closed-case summaries stored as embeddings on the graph itself, TigerGraph's native vector
search, not a separate vector database." Then: "and this case just got written back the same way -- the next
investigation that touches this device or this customer will find it."

## 7. Close (15s)
"Every number here traces to a query or a document. The LLM never decided whether this was fraud -- it explained
what the graph and the policy already decided, and wrote the report."

---

**If something breaks live**: fall back to the pre-generated `cases/*.json` files and the dashboard's static
case view -- every case in `cases/` is a real run against the live graph, not a mock.
