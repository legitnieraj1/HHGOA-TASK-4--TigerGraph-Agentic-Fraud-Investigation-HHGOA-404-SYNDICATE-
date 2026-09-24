# Screen recording checklist

`demo_script.md` has the narration/talking points. This is the operational shot list — exact clicks, exact
case IDs, in order — so the recording maps cleanly onto the rubric (Investigation accuracy 25%, Next best
action 25%, Case summary/explainability 10%, Agentic design 15%, Innovation 15%, Demo 10%).

Target length: **3-5 min**. Record in one continuous take if you can — a clean take beats a perfectly-edited
one for a hackathon demo; cut later only if something visibly breaks.

## Before you hit record

1. `pkill -f "uvicorn api.main"` then restart fresh: `.venv/bin/uvicorn api.main:app --port 8080` — a cold
   server means the first click has the "Loading weights" embedding-model delay, not mid-demo. Let it sit
   idle ~20s after startup so Savanna's had a chance to be awake, then load `127.0.0.1:8080` in the browser
   **before** you start recording, and click around once so nothing first-loads on camera.
2. Full-screen the browser window. Hide bookmarks bar, close other tabs, silence notifications (Do Not
   Disturb on).
3. Turn on cursor highlighting / click visualization if your recorder supports it (QuickTime doesn't
   natively — Cmd+Shift+5 has no click-highlight; if you want it, use a tool like CleanShot or just narrate
   what you're clicking since the case list gives clear visual feedback on selection anyway).
4. Record at 1080p+, system audio off, mic on, external mic if you have one — voice clarity matters more
   than video bitrate for a judging panel skimming submissions.
5. Have this file's case IDs typed into a scratch note so you're not hunting for them live.

## Shot list

### 1. Cold open — the problem (0:00–0:20)
No UI yet, or the case list on screen while you talk.
> "Half of these alerts are legitimate. A model that blocks everything scores badly; a bank that never blocks
> anything eats the fraud. This agent decides which is which, asks for more evidence when it doesn't know,
> and only acts within what it's actually allowed to."

### 2. Case list + one closed example (0:20–0:50)
- Scroll the left case list slowly — 20 real cases, mix of `legitimate` (green) / `fraud` (red) pills, real
  dollar exposure, `p=` fraud probability visible on every row.
- Click **HHG-003**. Point at:
  - the **timeline strip** (trigger → evidence(N) → assess → evidence requests → actions → resolution)
  - the **uncertainty meter** — say explicitly: "this isn't the bank's own risk score — on this dataset that
    score is actually *inverted* against real outcomes, 0.058 AUC. This is a propensity model calibrated on
    5,565 closed cases, blended with graph pattern detection."

### 3. Evidence loop + NBA before/after — use **HHG-007** (0:50–1:50)
This is the one case that visibly hits both the evidence-request loop AND a changed NBA in one view.
- Click **HHG-007** (`account_takeover`, p=0.85).
- Scroll to **evidence**: point at 1-2 `GRAPH · QUERY:...` items — say each evidence claim cites the exact
  query it came from, not asserted.
- Scroll to the **evidence request** — point at `assumed_response`: "this dataset doesn't give real customer
  replies, so the response is a documented, deterministic function, not hidden."
- Scroll to **next best actions**: show `initial` vs `final` side by side, and the **what_changed** line —
  the recommendation moved after that evidence came in.
- Point at the `BLOCK_CARD` action's **L1** route badge → click **Approve**. Say: "only `auto`-route actions
  execute themselves. Anything with real exposure, a person clicks yes."

### 4. SAR filing — use **HHG-006** (1:50–2:35)
- Click **HHG-006** (`undocumented` structuring pattern, p=0.92, exposure $1,427.12).
- Point at the pattern description: this is one of the **undocumented** pattern detectors (device-ring +
  sliding-window structuring) — not one of the five typologies the dataset names, found independently.
  Call this out as the innovation point.
- Scroll to the **SAR narrative**. Say: "follows FinCEN's five-W-plus-how structure, grounded in the real
  guidance document — and every fact in it traces to a query or policy clause in the evidence list right
  above."

### 5. Case memory — use **HHG-014** (2:35–3:10)
- Click **HHG-014** (`undocumented` device-ring, p=0.86, SAR filed).
- Point at **similar prior cases**: `CC-4241`, `CC-3954`, `CC-2675`. Say: "not keyword matches — semantic
  vector search over 5,565 closed-case embeddings, stored as native vectors on the graph itself, not a
  separate vector database."
- Say: "and this case just got written back the same way — `InvestigationCase` vertex, `SIMILAR_TO` edges.
  The next investigation on this device or customer finds it."

### 6. Live trigger panel — the agentic centerpiece (3:10–4:10)
This is the part that proves it's a live agent against the running graph, not a static file viewer.
- Switch to the right-hand **conversational panel**. Fill in (these are real, verified-working values):
  - Flagged transaction id: `3514030`
  - Card id: `C12382-K1`
  - Customer id: `C12382`
  - Reason: `analyst spotted unusual activity, please review`
- Click **Investigate**. While it runs (~15-30s live against Savanna), talk over it:
  > "This just fired a real LangGraph run — trigger, evidence gathering against 14 installed GSQL queries,
  > pattern detection, GraphRAG retrieval, the policy engine, and an LLM call that only writes the
  > explanation — it never decides fraud or not. That's deterministic."
- When it resolves, point at the new case appearing at the top of the case list and open it — same full
  structure as the pre-generated cases, generated live.

### 7. Close (4:10–4:30)
> "Every number on this screen traces to a graph query or a policy document. The agent recommends, a human
> approves anything that matters, and every closed case becomes memory for the next one."

## If something breaks live

Don't stop recording. Say "let me fall back to a saved run" and open the same case ID from the left list
instead of the live panel — every `cases/HHG-*.json` is a real run against the live graph already, so this
isn't faking anything, just skipping the live network round-trip on camera.

## After recording

- Trim dead air at start/end only — don't cut mid-sentence explanations, judges want the reasoning.
- Export at reasonable size for upload (H.264 mp4, ~1080p, doesn't need to be huge).
- Upload wherever the submission form asks (YouTube unlisted is the safe default if the form wants a link
  rather than a direct file — captions/auto-transcript are a bonus, not required).
