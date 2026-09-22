# NOTES.md - running decision log

Owner: Nieraj. Spec: `../prompt.md`. Data: `../datasets/` (symlinked into `data/raw/`, git-ignored).
Rule: the dataset README wins over prompt.md on data semantics and answer format.

## Phase 0 (recon) - DONE 2026-09-21

### Verified counts (scripts/00_profile.py, DuckDB, matches README)
- transactions 590,742 rows x 397 cols (393 Vesta + `customer_id`, `ts`, `channel`, `risk_score`)
- identity 144,432 rows x 41 cols, 1:1 subset of transactions on `TransactionID` (all online)
- closed_cases 5,565 (4,665 confirmed_fraud / 900 cleared), opened 2016-07-02 .. 2016-11-02
- case_pack 20 (Nov 12 - Dec 29). 13,553 customers. Timeline 2016-07-02 .. 2016-12-31
- Risk column is `risk_score` (0-1). Median 0.12, p90 0.38, p99 0.83. ~28k txns >= 0.7.
- `channel`: W = in_person (439,670, zero identity rows); C/H/R/S = online (151,072, 144,432 have identity)

### DERIVED: card_id (not a column in transactions.csv)
`card_id = customer_id || '-K' || dense_rank() OVER (PARTITION BY customer_id ORDER BY card6 ASC NULLS FIRST)`
- Found by search; validated 14,955/14,955 closed-case txn links and 20/20 case-pack flagged txns. 0 mismatches.
- `card1` is 1:1 with customer (13,553 distinct), so `customer_id` == card1 grouping.
- 14,317 cards total (K1 13,553 / K2 760 / K3 4). `card4` never varies within a (customer, card6), so
  (card4, card6) gives the same rank except 1 extra card. Using card6-only.
- NOTE (corrected 2026-09-21): an earlier guess that organiser-seeded rows have TransactionID > 7.5M was wrong (0 rows; the 7.8M values were TransactionDT seconds). Rows with NULL card6 (1,571 txns) land on K1 by the NULLS-FIRST rule. Seeded rows cannot be identified by ID; do not assume they can.

### Prompt vs README conflicts (README followed)
| # | prompt.md says | README says | Decision |
|---|---|---|---|
| 1 | Mock action names (`block_transaction`, `file_sar`, ...) | Policy action identifiers: `ALLOW_TRANSACTION`, `DECLINE_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `BLOCK_CARD`, `BLOCK_ALL_CARDS`, `GENERATE_REPORT`, `CREATE_CASE`, `FILE_REPORT`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD` | Use README ids exactly everywhere (answer files, policy engine, graph `Action` nodes) |
| 2 | Answer files in `outputs/cases/` | "a folder called `cases/` in your repository" | Write to repo-root `cases/` |
| 3 | Routes: auto / L1 / L2 implied | `auto`, `L1` (DECLINE_TRANSACTION; BLOCK_CARD <= $2,500), `L2` (BLOCK_CARD > $2,500; BLOCK_ALL_CARDS; FILE_REPORT) | Implement exactly in `policy_engine.py` |
| 4 | Loop cap <= 3 rounds, generic uncertainty | Policy s6 stop rules: p>=0.85 or <=0.15 with >=2 independent evidence; verification settles; no further change | Implement s6 verbatim + hard cap |
| 5 | Vertices Device/IpConn/Address... | `DeviceProfile` = DeviceInfo+OS(id_30)+browser(id_31)+screen(id_33), `BillingRegion`=addr1, `EmailDomain`, `ClosedCase` | Use README schema as base |
| 6 | Agent "executes" mock actions | Only `auto` actions executable; L1/L2 recommended and wait | Same, enforced in policy engine |
| 7 | Evidence requests simulated | Must list in `evidence_requests` with `assumed_response` | Include per README |

### README rules to remember (graded)
- Case opens at fraud prob >= 0.30, on any evidence request, or on customer dispute (s3a).
- SAR (`FILE_REPORT`) only when fraud confirmed/strongly suspected AND (exposure > $1,000 OR shared device/region/other-card fraud OR coordinated/undocumented). `sar.file` must agree with `FILE_REPORT` in `final`.
- R1 verify before block when single signal and p < 0.70. R10 BLOCK_ALL_CARDS only with >= 2 confirmed-fraud cards or confirmed credential compromise.
- Half the cases are legitimate. Blocking everything scores badly. `uncertain` verdict is valid on ambiguous cases if R1/R8 followed.
- Every ID in answers must exist in the dataset. Never use public Kaggle IEEE-CIS files (disqualification).
- Answer JSON: top-level `case_id, case, evidence_requests, next_best_actions{initial,final,what_changed}, sar, stop_reason, tool_calls, tokens, latency_s`. Full spec in `outputs/ANSWER_FORMAT.md`.
- Closed-case pattern mix (calibration/memory): CNP 1404, ATO 1205, CNP-new-device 1076, out-of-region 955, card_testing 16, undocumented 9 (all filed reports), cleared 900.

### Environment
- Python 3.11.16 venv at `.venv` (duckdb 1.5.5, pandas 3.0.6). System python is 3.9, do not use.
- 16 GB RAM, ~23 GB free disk. Docker via colima.
- NOT yet available: TigerGraph instance, `ANTHROPIC_API_KEY`, embedding key. See open items.

## Open items / blockers
- [ ] TigerGraph target: Savanna signup (needs Nieraj) or Community Edition in Docker (colima).
- [ ] `ANTHROPIC_API_KEY` (+ embedding provider key) into `.env`.

## Phase 1 prep - Savanna connected 2026-09-21
- Workspace `MyWorkspace` (R/W, TigerGraph 4.2.5, 2 vCPU / 16 GiB), auto-suspend 20 min + auto-resume on (set in Workspace Configuration > Advanced Settings).
- Host: `tg-70490eff-1a5c-4c6e-a767-0ea7bf6c9db2.tg-2635877100.i.tgcloud.io` (found via Admin Portal URL `domain=` param; the Connect dropdown does not show it).
- Auth: secret -> `POST /gsql/v1/tokens {"secret":..., "lifetime":"3600"}`. Omit `graph` (the secret alias `MyDatabase` is a label, not a graph name; passing it returns "Graph MyDatabase not found"). Token is global (user is superuser). Tokens expire, client must refresh.
- GSQL over REST: `POST /gsql/v1/statements` with `Authorization: Bearer <token>`, `Content-Type: text/plain`.
- Existing graph `Transaction_Fraud` is TigerGraph's pre-loaded sample. Left untouched. We create our own `FraudGraph`.
- Secret was pasted in chat once: rotate before submission (Database Secrets), update `.env`.

## Phase 1 - graph schema + ingestion - DONE 2026-09-21
- Graph `FraudGraph` (local schema, so no collision with the sample `Transaction_Fraud` global types). Built by `scripts/10_setup_graph.py` from `tigergraph/spec.py` (single source of truth for columns, DDL, export SQL, loading jobs).
- Vertices: Customer, Card, Transaction (73 attrs), DeviceProfile, EmailDomain, BillingRegion, ClosedCase, plus agent-written InvestigationCase, Action, PolicyDoc. Vector attrs (`emb`, 384-d COSINE, HNSW) on ClosedCase, PolicyDoc, InvestigationCase.
- Edges (each with a reverse edge): OWNS, MADE, FROM_DEVICE, PURCHASER_EMAIL, RECIPIENT_EMAIL, BILLED_IN, NEXT(gap_s), INVOLVES, CC_ON_CARD, CC_CONNECTED_TO, HAS_EVIDENCE, CASE_ON_CARD, CASE_CONNECTED_TO, CASE_DEVICE, TOOK_ACTION, SIMILAR_TO(score).
- Reconciled exactly vs export (`scripts/25_verify_load.py`): Customer 13,553 | Card 14,317 | Transaction 590,742 | DeviceProfile 9,705 | EmailDomain 60 | BillingRegion 332 | ClosedCase 5,565; MADE 590,742 | NEXT 576,425 | OWNS 14,317 | INVOLVES 14,955 | CC_ON_CARD 5,565 | CC_CONNECTED_TO 92 | FROM_DEVICE 140,784 | BILLED_IN 525,003 | PURCHASER_EMAIL 496,262 | RECIPIENT_EMAIL 137,453.
- Spot checks vs DuckDB pass (txn 3514030, customers C12382/C08623/C13487, CC-0004).

### Decisions and gotchas
- V1-V339 are NOT in the graph (size/speed on a 2 vCPU workspace). They stay in `data/profile/profile.duckdb`; the agent reads them via a `get_features(txn_id)` tool and must cite them as unnamed model features (README).
- Missing numerics are stored as sentinel `-1` (never 0); missing strings as `""`. Every query/tool must treat `-1` as NULL. `-1` for `D*` cols means "not recorded".
- `DeviceProfile` key = `DeviceInfo | id_30 | id_31 | id_33` (README example format; missing part = empty string). Device IDs contain `/` so REST path GETs on DeviceProfile fail: use GSQL queries.
- Reserved words: `proxy` cannot be an attribute (renamed `ip_proxy`).
- Local schema-change jobs: a vertex must exist before `ALTER ... ADD VECTOR ATTRIBUTE` (separate job). Each job ~36 s.
- Loading jobs: no `CREATE OR REPLACE`; use `DROP JOB` then `CREATE`. Ingest is eventually consistent (Kafka): counts lag, verify by polling.
- REST `/restpp/ddl` load: a 10k-row chunk hit a gateway 504 once; loader now retries with backoff and uses 5k chunks. Whole load ~7 min.
- Timing: case-pack `opened_at` is later than the flagged txn `ts` (e.g. HHG-001: txn 2016-12-04 19:55, opened 12-05 01:55). Investigations must only use history up to the flagged txn (no future leakage) when building baselines.

## LLM choice - 2026-09-21 (swap from spec's Claude, allowed by spec s2 "document the swap")
- Anthropic key not available; the AgentRouter key is rejected for direct API use (401 "unauthorized client"), and we do not spoof client identity.
- Using NVIDIA NIM free endpoint (`https://integrate.api.nvidia.com/v1`, OpenAI-compatible). Probed 2026-09-21:
  - WORKS: `nvidia/nemotron-3-ultra-550b-a55b` (tool call ok 2.1 s), `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (JSON ok).
  - Hangs on first request (cold/unavailable): `nemotron-3.5-lightning-30b-a3b`, `glm-5.3(-flash)`, `gemma-4-31b-it`, `gpt-oss-20b`, `kimi-k3`.
  - End-of-life (HTTP 410): `llama-3.3-70b-instruct`, `gpt-oss-120b`, `qwen3-next-80b`.
  - Free tier is shared: intermittent 503 "overloaded" / "worker request limit reached".
- Primary `LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b`; `LLM_FALLBACK_MODELS=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`. Optional last fallback: Gemini 3 Flash if a key is added.
- Design consequences for `llm/` wrapper: (1) retry with backoff + model fallback chain on 5xx/timeouts, hard per-call timeout (no default OpenAI retries), (2) on-disk cache keyed by (model, messages, tools) so re-running the 20-case benchmark is deterministic and cheap, (3) LLM only reasons/selects tools/explains; every fraud signal, probability input and action route is computed deterministically from graph queries + policy engine, and the explanation has a templated fallback if the LLM is unreachable, so the benchmark can always be produced.
- Reasoning models may return empty `content` with `reasoning_content`; wrapper must handle that and set generous `max_tokens`.
- NVIDIA key was pasted in chat: rotate at build.nvidia.com before submission.

### LLM chain update - 2026-09-21 (supersedes primary model above)
- Gemini key works (model list OK). Probed via OpenAI-compatible endpoint, tool call + JSON mode:
  - `gemini-3.6-flash`: tool OK 5.6 s, JSON OK 20 s  -> PRIMARY
  - `gemini-3.1-flash-lite`: tool OK, JSON OK 1.4 s   -> fallback 1
  - `gemini-3.8-flash` 503 overloaded, `gemini-3.7-flash` timeout, `gemini-flash-latest` JSON 503, `gemini-2.5-flash` retired for new users (404).
- Chain in `.env`: `LLM_CHAIN=gemini:gemini-3.6-flash, gemini:gemini-3.1-flash-lite, nvidia:nemotron-3-ultra-550b-a55b, nvidia:nemotron-3-nano-omni-30b-a3b-reasoning`. Wrapper tries in order on 5xx/timeout.
- Gemini key was pasted in chat: rotate before submission (aistudio.google.com/apikey). Rotate all of: TG secret, NVIDIA key, Gemini key, AgentRouter key.

## Phase 2 calibration findings - 2026-09-21 (DuckDB prototypes on closed cases; GSQL queries mirror these features)
### Data facts that shape the detectors
- **risk_score is not a fraud signal on the case population**: fraud-vs-cleared AUC 0.058 (inverted). Cleared alerts avg risk 0.88, fraud cases avg 0.47. Over ALL txns Oct it is weakly informative (AUC 0.865) but on risk>=0.5 alerts it is 0.59.
- **Pattern labels follow episode composition**: CNP = all online + no `New` device flag (100%/0%); CNP-new-device = all online + New (100%); OOR = all in-person (100%); ATO = 81% all-in-person, 19% mixed channel. **ATO vs OOR is NOT separable** by any episode feature I found (depth-3 tree 67% vs 56% base). Agent must report ATO/OOR with honest low confidence; both lead to BLOCK_CARD + CREATE_CASE so actions are unaffected.
- **Region novelty does not define OOR**: 77% of OOR key txns have the region in the card's prior history; cleared 'travel' cases look the same (19% vs 23% zero-history). Do not use region novelty as a decisive signal.
- **Cleared cases** (900): 716 'travel' (mostly online+New device in the data), 158 'new phone' (online, New device), 26 'unusual amount' (in-person). All single-txn, avg risk 0.88. Reasons in notes are not observable in txn features.
- **Episode span is long**: median 0.0h (CNP) to 27h (ATO), p95 up to 520h. Fraud txns are interleaved with legit ones on the same card.
### Fraud-propensity model (`detectors/propensity.py`, `scripts/32_train_propensity.py`)
- HistGradientBoosting over 408 features: Vesta C/D/M/V/id (unnamed, cited as such) + history-only graph features (`scripts/31_graph_features.py`: burst counts, first-seen device/region/product on card, other cards on same device, amount ratio). Trained ONLY on closed-case labels (1 = txn in confirmed_fraud case, 0 = every other Jul-Oct txn incl. cleared). No public Kaggle data used.
- 5-fold GroupKFold by customer: OOF AUC 0.947, AP 0.712. Time split (train Jul-Sep, test Oct): AUC 0.956; on Oct risk>=0.5: AUC 0.917 vs 0.593 for risk_score. Graph features add +0.009 AP.
- Isotonic-calibrated `p_cal`: on ALL risk>=0.5 txns bins track truth (pred 0.618 vs actual 0.682 in 0.5-0.7; 0.931 vs 0.940 in 0.85-1). Cleared alerts get mean p 0.07 (model correctly discounts risk 0.88).
- Key-txn fraud-vs-cleared AUC 0.817. Weakness: in-person ATO/OOR fraud median p only 0.14 (looks normal to Vesta features); undocumented median 0.13. Graph/rule detectors and the uncertainty loop must cover these.
### Episode reconstruction (from the flagged/key txn)
- Rule: same-card txns within +-24h with p_cal >= 0.5 and same channel, plus the key txn. Precision 0.987, recall 0.80, F1 0.885 (key-only F1 0.823). Longer windows trade precision for recall (72h: 0.93/0.84).
### Undocumented patterns (README: scored if found)
- **Threshold structuring**: 5 closed cases, 4 online purchases within ~27 min, each $465-$492 (just under $500), total ~$1.9k, all ProductCD C. Model p 0.04-0.54 (blind). Rule: >=3 online purchases within 60 min, each in [0.8T, T) for T in {250,500,1000,2000}.
- **Shared-device ring**: device `SM-G935F Build/NRD90M | Android 7.0 | chrome 62.0 for android | 1920x1080` behind `IP_PROXY:ANONYMOUS`, `New` on each account: 52 cards, 114 txns, 2016-08-15..2016-12-04, only 10 fraud txns closed so far. Model p 0.01-0.04 (blind). Most of the ring is still open in Nov-Dec (HHG-014 analyst request). Graph hub detection is required.
- Data-artifact observation (not used as evidence): injected undocumented rows have timestamps on exact minutes (seconds = 00).
### Card testing
- The 16 closed testing cases are tiny amounts (<$1) scattered over days, not the README's 3-in-an-hour. Loose rule (>=3 online < $5 in 72h before a >=$10 purchase) is weak: fires on 5,054 clean txns vs 89 true (LR ~5). Strict README rule (>=3 tiny < $5 within 60 min then a larger purchase) treated as strong. Both encoded, with different match strengths.

## Phase 2 continued: GSQL queries installed + evidence assembler - DONE 2026-09-22

### 12 installed queries (`tigergraph/queries/*.gsql`, `scripts/35_install_queries.py`)
Evidence: `get_transaction`, `card_window`, `card_behaviour`, `customer_profile` (prior closed cases, most-recent-first
via HeapAccum -- feeds case memory), `card_neighbourhood`, `trace_chain`. Patterns: `pattern_card_testing`,
`pattern_structuring`, `pattern_device_ring`, `device_hubs` (global ring scan). Clusters: `region_cluster`,
`email_neighbors`. All validated against DuckDB ground truth (exact row/count match) and against closed-case
positives/negatives. `scripts/35_install_queries.py` now verifies via `SHOW QUERY *` that every requested query is
actually `# installed` (not `# draft`) -- caught `card_behaviour` silently failing install (a `to_int()` call that
doesn't exist in this GSQL version; INT/INT is already integer division, fixed by removing the wrapper) after its
error got hidden by output truncation in an earlier multi-query install. Lesson: never trust an install summary
count without per-name verification.

### Gotchas hit writing GSQL (Savanna 4.2.5)
- `to_vertex(id, "Type")` is not valid in a `{...}` vertex-set literal; use typed params (`VERTEX<Card> card`) instead.
- `HeapAccum` has no `.get()`/indexing -- drain with `WHILE h.size()>0 DO list += h.top(); h.pop(); END` into a
  `ListAccum` first, then index that.
- `FILTER (...)` must appear before `OVER (...)` in a window function, not after.
- `proxy` is a reserved keyword as an attribute name (renamed `ip_proxy`, Phase 1).
- `to_int()` doesn't exist; integer division of two INTs is already INT in GSQL.
- Local schema-change jobs need the vertex to exist before `ALTER ... ADD VECTOR ATTRIBUTE` (separate job, Phase 1).
- REST vertex-id params must be percent-encoded manually (`quote(v, safe='')`); `requests`' default `params=` encodes
  spaces as `+`, which breaks device-key ids that contain spaces, `/` and `|` (`tigergraph/client.py: run_query`).

### Workspace wake behaviour (auto-suspend 20 min / auto-resume, set in Phase 1)
- First request after idle gets a `502` "Starting workspace" HTML page for ~15-20s while it wakes; a request can
  even hit `No route to host` for a few seconds. `TG.wake()` polls `/restpp/echo` for valid JSON before proceeding;
  `TG._req()` now retries once on 502/503 through `wake()` (previously only retried on 401). Token calls call
  `wake()` first. Not just the REST gateway wakes progressively -- the query engine (GPE/GSE) can lag a few seconds
  behind the gateway even after `/restpp/echo` returns 200 (hit one 300s query timeout right after a cold wake;
  resolved itself once `stats()` confirmed the engine was warm). No code change for that last part; noted here in
  case a query call needs its own wake-confirmation later.

### `detectors/patterns.py` -- deterministic classifier (LLM never computes this)
- `classify(episode, structuring, testing, ring)`: composition rule (channel mix + New-device flag) gets CNP and
  CNP-new-device 100% right on true episodes; card_testing/structuring/ring are checked first as override rules.
- `ring_strength()`: a device counts as a ring only if it is `New` on >=90% and proxied on >=80% of its activity
  across >=5 cards (not just "shared by many cards" -- see false-positive fix below).
- `apply_memory_prior(result, prior_fraud_patterns)`: for the ATO-vs-OOR tie (composition alone can't separate them,
  see earlier note), nudges toward the most recent confirmed-fraud pattern on the SAME card/customer when it
  disagrees with the rule call. Validated on all 4,656 true episodes (excluding undocumented): rule alone 76.1%,
  rule+memory 84.4% (ATO recall alone: 29.6% -> 59.5%). This is the case-memory signal that satisfies acceptance
  criterion #10 ("similar prior cases change a recommendation") for the ATO/OOR ambiguity specifically; broader
  semantic similar-case retrieval is a separate GraphRAG vector-search component (Phase 4, not yet built).

### `detectors/evidence.py` -- evidence bundle assembler (Phase 5's gather_evidence node will call this)
- `build(tg, txn_id, card_id, customer_id)`: pulls the flagged txn, reconstructs the episode (`card_window` +-24h +
  local `pred` table lookup), runs testing/structuring/ring probes, pulls card/customer baselines and case memory,
  classifies the pattern, and returns an `evidence` list already shaped like the answer format's
  `case.evidence[]` (`claim`, `source`, `ref`, `entity_ids`).
- **Found and fixed a real evidence-honesty bug before it could reach an answer file**: `card_neighbourhood`'s raw
  "other cards sharing a device that have a fraud history" is NOT a signal -- 10.1% of all 14,317 cards (1,441) have
  >=1 confirmed-fraud closed case, so on a popular device with hundreds of users that count is large by base rate
  alone (observed 160/14,317... no, 160 cards on one popular device in a single smoke-test case). Citing it would
  have been an unsupported claim (policy s.7). Fixed: only `ring_strength()`'s calibrated, filtered signal
  (New+proxied, 0 FP across 25 closed-case negatives incl. cleared) feeds `connected_card_ids` / device evidence.
- Ran on all 20 case-pack rows end to end against the live graph: 20/20 succeeded, ~8.5s and ~9.5 graph calls per
  case (171s / 191 calls total). HHG-014 (the analyst_request case, explicitly "several cards show purchases from
  the same unusual device profile") correctly comes back `undocumented`, confidence 0.95, ring detected -- exactly
  what the trigger text describes. Preliminary pattern spread across the 20 cases (pre-LLM, pre-uncertainty-loop,
  subject to change once evidence_requests/memory/LLM synthesis run): 8x card_not_present_new_device, 3x
  out_of_region_use, 2x card_not_present_fraud, 2x account_takeover, 2x undocumented, 1x card_testing (loose),
  1x flagged for further evidence-gathering (low episode signal). Sanity-checked that 6 borderline cases with a
  populated `ring` bundle (common phone models / OS+browser combos, share_new 41-64%, share_proxy ~0%) were
  correctly rejected by `ring_strength()` and did NOT flip to `undocumented` -- confirms the detector isn't
  over-firing on "popular new phone this holiday season" coincidences, which the Jul-Oct-only calibration sample
  could plausibly have missed since the case pack is Nov-Dec.

## Phase 3: TigerGraph MCP - DONE 2026-09-22

- Used the official `pip install tigergraph-mcp` (v1.0.3, pyTigerGraph 2.0.4) rather than hand-rolling a
  generic GSQL/REST tool wrapper -- it already exposes exactly what's needed: `run_installed_query` (our 12
  queries), `gsql` (raw), `get_neighbors`, vector ops (`upsert_vectors`, `search_top_k_similarity`,
  `add_vector_attribute` -- for Phase 4), schema/stats tools. 69 tools total. Cloned to `mcp/tigergraph-mcp/`
  for reference/docs only (git-ignored, its own nested `.git`); not vendored into our repo.
- Config: `mcp/.env` (git-ignored) with `TG_HOST` (needs `https://` scheme, unlike our root `.env`),
  `TG_GRAPHNAME=FraudGraph`, `TG_SECRET`, `TG_TGCLOUD=true`. Verified pyTigerGraph's secret-based auth
  (`gsqlSecret=`) against Savanna directly: mints a token via the same `/gsql/v1/tokens` flow our own
  `tigergraph.client.TG` uses, `getVertexCount("Customer")` returned 13,553 (matches Phase 1 reconciliation).
  Subject to the same wake-latency behaviour as our own client (NOTES.md Phase 2): the first call after idle
  can hit a 502 even a few seconds after our own `wake()` confirms `/restpp/echo` is ready, because the GSQL
  auth backend can lag slightly behind the REST gateway. No fix needed here, just don't be surprised by one
  transient retry.
- `mcp/launch.sh` starts the server over stdio; `agent/tools/graph_mcp.py` opens ONE session per agent run
  (`graph_mcp_tools()` context manager) and loads LangChain tool objects via `langchain-mcp-adapters`, per the
  server's own "reuse one process" guidance -- not a fresh subprocess per call.

### Important finding: Gemini 3.x + OpenAI-compat endpoint breaks multi-turn tool calling
- `ChatOpenAI(base_url=GEMINI_BASE_URL, ...)` (the wrapper used for the earlier LLM-chain probing, NOTES.md
  "LLM chain update") works for a SINGLE tool call but fails the *second* turn of a multi-step tool-calling
  loop: `400 Function call is missing a thought_signature`. Gemini 3's function-calling protocol requires an
  opaque `thought_signature` to be echoed back on every subsequent turn, and LangChain's generic OpenAI chat
  wrapper doesn't preserve that Gemini-specific field.
- **Fix: use `langchain-google-genai`'s native `ChatGoogleGenerativeAI` for Gemini**, not the OpenAI-compat
  shim, for ANY node that does more than one tool call in a row (which is most of the agent). Installed
  (`langchain-google-genai==4.4.0`). Confirmed working through a real multi-step MCP tool-calling loop
  (`create_react_agent` + 2 sequential `run_installed_query` calls, correct results both times, even
  self-recovered from one transient "Access Denied, empty token" race on the very first call after the MCP
  server process started).
- **Consequence for `llm/` (Phase 5)**: the provider wrapper cannot be "one OpenAI-compatible client, swap
  base_url" as originally planned. It needs a per-provider LangChain chat-model class: `ChatGoogleGenerativeAI`
  for Gemini, `ChatOpenAI` (base_url override) for NVIDIA -- NVIDIA's raw `chat.completions` API worked fine
  for single-turn tool calls in the earlier probe, but has not yet been tested through a multi-step LangGraph
  tool loop; test that before relying on it as the fallback for agent nodes, not just for JSON-only synthesis
  calls. The single-shot JSON-mode and plain-text calls (explanation, SAR narrative) are unaffected either way.
- `create_react_agent` is deprecated in LangGraph 1.0 in favour of `langchain.agents.create_agent`; noted for
  Phase 5, not fixed now (works fine, just a deprecation warning).

### Phase 3 check (spec-required)
`tests/test_mcp_direct_smoke.py`: direct (no-LLM) `run_installed_query` calls for `card_neighbourhood` and
`trace_chain` through the MCP server -- results match the values already validated in Phase 2 exactly.
`tests/test_mcp_agent_smoke.py`: a real LLM (Gemini 3.6 Flash, native SDK) tool-calls the MCP server for the
same two queries and reports back correctly: "Card C03528-K1... `SM-G935F...`: 21 other cards... Previous
Transaction IDs: 3513814, 3512936; Next: 3514461, 3515241" -- exact match to the manually-verified numbers.

## Phase 4: GraphRAG (policy + case memory) - DONE 2026-09-22

### Chunking (`graphrag/chunk.py`)
29 chunks from `data/policy/*.md` (all extracted verbatim from the README in Phase 0, plus one new file):
10 policy rules (`policy:R1`..`policy:R10`, split out of the "### 3. Rules" section individually -- R10's bold
markup lacks R1-R9's trailing period before `**`, a real parsing gotcha, fixed), 8 other policy sections
(`policy:0,1,2,3a,3b,4,5,6,7`), 5 known patterns (`pattern:card_testing` etc.), 3 regulatory chunks, 2 misc
(glossary, things-to-know). Chunk ids are stable and human-legible so a citation can read `ref: "policy:R5"`
directly (policy s.7: "cite the rule number").

### Regulatory grounding (`data/policy/regulatory_guidance.md`, new)
The README only lists regulator document titles/links, not text. Fetched and read two of the most operationally
relevant ones directly (2026-09-22) rather than fabricate their content: **FinCEN's SAR Narrative Guidance**
(the five W's + How, and the introduction/body/conclusion structure -- this is the actual source for
`sar.narrative`'s required shape) via PDF page images (WebFetch couldn't parse the PDF's compressed streams;
Read tool + `pdftoppm`, installed via `brew install poppler`, rendered pages as images instead), and **FinCEN's
Account Takeover Advisory (FIN-2011-A016)** (red flags, SAR box-checking conventions) via WebFetch (HTML page,
fetched fine). The other ~11 regulatory references are indexed as title/agency pointers only, explicitly marked
as not fetched for content -- so nothing here is fabricated as verbatim regulatory text.

### Embeddings (`graphrag/embed.py`)
Local `sentence-transformers/all-MiniLM-L6-v2`, 384-dim (matches `EMB_DIM` in `tigergraph/spec.py`), normalized.
No API cost, no network dependency at query time. `EMBEDDING_PROVIDER=local` in `.env` confirmed as the choice.

### Vector search queries + a real bug caught before it degraded retrieval silently
`tigergraph/queries/vector_search_policy.gsql` / `vector_search_cases.gsql`: `vectorSearch({Type.emb}, vec, k,
{distance_map: @@d})`, `SYNTAX v3`. Two gotchas:
- A `LIST<FLOAT>` query parameter (384 floats) doesn't work as a GET query string (repeated-key or single-value
  forms both failed with type errors); switched `TG.run_query()` to POST with a JSON body whenever any param is
  a list/tuple, scalar-only calls still use GET. Fixed in `tigergraph/client.py`.
- **`vectorSearch`'s PRINTed vertex order is NOT sorted by distance** -- verified empirically: for a card-testing
  query the raw PRINT order was `[pattern:card_testing, policy:R5, policy:R10, policy:R4, ...]` while the actual
  distances (looked up from `@@distances`) were `[0.531, 0.289, 0.538, 0.411, ...]` -- policy:R5, the closest
  match, was NOT first in the unsorted list. `graphrag/retrieve.py` always sorts by the returned `distance_map`
  before use; anything reading `vectorSearch` output directly (including from the MCP `search_top_k_similarity`
  tool in Phase 5) must do the same or silently misrank results. COSINE distance confirmed lower-is-closer (the
  `card_not_present_new_device` chunk, whose own text says "device... New... behind a proxy", correctly has the
  lowest distance for a device+proxy query).

### Phase 4 check (spec-required: "retrieval returns the right policy clause for a shared-device ring and for
a card-testing burst")
- Card-testing query -> `policy:R5` ranks #1 of 6 (distance 0.289, next closest 0.411). Clean pass.
- Device-ring query -> `policy:R6` ("Shared origin") ranks #2 of 6 (distance 0.457, #1 is
  `pattern:card_not_present_new_device` at 0.361, topically adjacent -- also about New+proxy devices). Inside
  the default context window (`synthesize_context`'s `max_policy=4`), so the LLM sees it either way. Honest
  pass, not a clean #1.
- Case memory: a device-ring-shaped query's #1 hit is `CC-2985`, one of the actual known ring cases found by
  rule-based detection in Phase 2 (`SM-G935F...` device, `undocumented` pattern) -- semantic and rule-based
  detection agree on the same case from two independent methods.

### Seeding (`scripts/40_seed_memory.py`, idempotent -- upsert overwrites)
29 `PolicyDoc` vectors + 5,565 `ClosedCase` vectors (embedded in 17s, upserted in 300-row batches via
`TG.upsert()` REST, not MCP -- MCP is for agent-runtime retrieval per the spec's tool-exposure requirement;
bulk seeding scripts use the direct client for speed/reliability, already proven in Phase 1/2). Vector index
rebuild (`GET /restpp/vector/status`) went from `Rebuild_processing` to `Ready_for_query` within the seeding
run; search already returned correct results even mid-rebuild.

### `graphrag/retrieve.py` -- what Phase 5's gather_evidence node will call
`retrieve(tg, pattern_result, flagged_txn_summary)`: builds a query from the case's suspected pattern + evidence
reasons (not just the pattern label -- semantic search does better on a descriptive sentence), searches both
PolicyDoc and ClosedCase vectors, returns a synthesized, already-cited context block
(`synthesize_context`) -- never raw rows or full documents, matching the spec's GraphRAG requirement.

## Phase 5: The LangGraph agent - DONE 2026-09-22

### Architecture decision: deterministic pipeline, LLM only for single-shot synthesis
The 8-node flow (trigger -> investigate -> gather_evidence -> assess_uncertainty <-> gather_more -> next_best_action
-> explain -> update_memory, `agent/graph.py`) is a real LangGraph `StateGraph` with a genuine conditional loop.
But INSIDE it, fraud detection, pattern classification, probability, and policy routing are 100% deterministic
Python (detectors/, agent/policy_engine.py, agent/uncertainty.py) -- the LLM is called exactly once per case,
in `explain`, for JSON-mode text synthesis (summary, pattern_description, stop_reason, SAR narrative) over
already-assembled evidence. No tool-calling loop in the graded 20-case pipeline. This was a deliberate call
given Phase 3's finding (Gemini 3.x breaks multi-turn tool calls over the OpenAI-compat shim): rather than fight
that in the pipeline that actually gets graded, real multi-turn MCP tool-calling is reserved for the UI's
conversational panel (Phase 7, not yet built), where a judge can ask ad-hoc questions live. `explain` falls back
to a template if every LLM provider fails (NOTES.md Phase 2/3), so the benchmark can always be produced.

### `llm/client.py`
Provider-chain (`.env LLM_CHAIN`), disk-cached by (model, messages, response_format) so re-running the 20-case
benchmark is free and deterministic. `generate()` (text) / `generate_json()` (JSON mode + one repair retry).

### `agent/policy_engine.py` -- the routing table + R1-R10, hand-coded from data/policy/fraud_policy.md exactly
`route_for()` implements s.2's table exactly (BLOCK_CARD's L1/L2 split at $2,500). `evaluate()` runs the rules in
priority order (R3/R2/R4/R7 branches on a verification response, else R1/R5/R6/R8/R9), returns a list of
`Recommendation(action, route, reason)` citing the rule number. `build_flags()` derives every rule input from
the evidence bundle so the initial and final NBA passes compute identically. Two DOCUMENTED, honest gaps given
what this dataset provides: **R7 can never fire** (no merchant identity, only a ProductCD category -- "same
merchant, same amount, monthly" isn't detectable), and `pending_auth` is proxied by trigger_type (risk_score =
before settlement) since there's no explicit pending/settled flag.

### `agent/uncertainty.py` -- fraud_probability + the stop rule
`fraud_probability = w * propensity + (1-w) * pattern_confidence`, where `w` is per-pattern (Phase 2 calibration:
propensity is well-calibrated for CNP/CNP-new-device/card_testing, but "blind" to in-person ATO/OOR and to
undocumented structuring/ring -- so those patterns lean on the (separately calibrated) pattern-confidence
instead). Stop rule matches policy s.6 exactly (>=0.85 or <=0.15 with >=2 independent evidence; a verification
response settles it; round cap as a last resort).

### A real design bug found and fixed via testing on closed cases (not just unit-level review)
Ran `scripts/50_run_case.py` on CC-0001 (confirmed_fraud, card_not_present_fraud) and CC-0003 (cleared,
$442.92 flagged at risk 0.91 -- exactly the worked "confirmed travel" example from README's Things To Know).
CC-0003 exposed a real bug: `no_reply_24h` was detected by checking for the substring `"no reply"` in the
simulated response text, but the actual text says `"No response... within 24 hours"` -- the check silently
never matched, so **policy R4 never fired**, and `gather_more` kept re-asking the identical `customer_validation`
question 3 times (hitting `MAX_ROUNDS`) with zero new information each round, since the deterministic simulator
is a pure function of already-known evidence and asking again cannot produce new information. Fixed at the root:
refactored `uncertainty.assess()` around a single `evidence_request_outcome` (`None | confirmed | denied |
no_reply | inconclusive`) where **every** non-None outcome is now terminal -- R4 explicitly defines the action
for "no reply" rather than asking again, and "inconclusive" hits policy s.6's third stop condition ("further
steps are unlikely to change the decision"). Both closed cases now resolve in exactly 1 round instead of 3,
matching the spirit of "investigations that continue past a defensible decision waste time" (policy s.6).
Also fixed a wording bug: `what_changed` said "the customer denied the transaction" even when the response came
via a failed step-up-auth challenge, not a direct customer denial -- now phrased per the actual evidence-request
type. Neither bug would have been caught by reading the code; both only showed up by actually running cases.

### `agent/tools/actions.py` -- mock action layer, deterministic simulated responses
Two categories: evidence-gathering (customer_validation / step_up_auth / analyst_info -- responses are a pure,
documented function of the agent's OWN current fraud-probability estimate, never a hidden label, satisfying
both README's "state the assumption" and prompt.md's "determinism for the demo") and policy-action execution
(only `auto`-route actions actually run; L1/L2 are recorded pending, gated by `policy_engine.is_executable()`).
Verified directly: on CC-0001, `BLOCK_CARD` (route L1) came back `executed: False, "PENDING L1 approval -- not
executed by the agent"`, `CREATE_CASE` (route auto) came back `executed: True` -- the "never execute an
approval-required action without approval" check the spec calls for, confirmed by inspection, not just by design.

### `agent/memory.py` -- writes the resolved case into the graph
Creates an embedded `InvestigationCase` vertex + `HAS_EVIDENCE`/`CASE_ON_CARD`/`CASE_DEVICE`/`TOOK_ACTION`/
`SIMILAR_TO` edges. Verified on CC-0001: the vertex and all edge types landed correctly, including three real
`SIMILAR_TO` links to `ClosedCase` vertices found by GraphRAG semantic retrieval (CC-2992, CC-3908, CC-2578) --
genuine case memory, queryable by the next investigation.

### Phase 5 check (spec-required): run on a confirmed-fraud closed case and a cleared closed case
- **CC-0001** (confirmed_fraud/card_not_present_fraud, true exposure $155.43, no report filed): agent reaches
  verdict=fraud, pattern=card_not_present_fraud, exposure=$155.43, sar.file=false -- all three match the ground
  truth exactly. BLOCK_CARD correctly withheld pending L1 approval.
- **CC-0003** (cleared -- the README's own "cardholder confirmed travel" example): agent reaches verdict=fraud
  at p=0.57 (single ambiguous risk-0.91 in-person txn, simulated no-reply). This DISAGREES with the true (hidden)
  outcome, and that's expected and acceptable: the agent has no way to observe "customer confirmed travel" --
  that fact isn't in the transaction data, only in the closed case's human-written outcome. What matters is that
  the PROCESS is defensible: R4 fired correctly on a genuine no-reply, the loop terminated in one round instead
  of wasting three, every action cites its rule, and BLOCK_CARD-class actions still wait for approval. The
  20 real exam cases have no visible ground truth either way -- this dev validation is about process soundness,
  not oracle accuracy.
- Uncertainty loop fires when signals are weak (both cases were "weak" at round 0, both triggered gather_more,
  both terminated in exactly one round after the fix above -- no infinite/wasteful looping).

## Phase 6: case memory eval - DONE 2026-09-22

Spec check: "Confirm retrieval of similar past cases materially changes recommendations... small eval showing
memory improves the assessment on a held-out closed case vs. memory disabled."

`scripts/45_memory_eval.py`: held out 1,580 confirmed-fraud closed cases (account_takeover / out_of_region_use,
the two patterns Phase 2 found are NOT separable from a single episode's behaviour alone -- exactly the
condition memory is meant to help) that each have at least one prior confirmed-fraud case on the same card.
Compared `detectors.patterns.classify()` alone (no memory) against `classify()` + `apply_memory_prior()` (same-
card case history):

| | accuracy | 
|---|---|
| without memory | 804/1580 = 0.509 |
| with memory | 1190/1580 = 0.753 |

Memory flipped 726 of 1,580 recommendations: fixed 556 wrong calls, broke 170 right ones (net +386, a clearly
positive and material effect, not noise). This is the case-memory ablation for the ATO/OOR pattern ambiguity
specifically. Separately, every live agent run (Phase 5) also shows GraphRAG semantic case retrieval
(`graphrag/retrieve.py`'s `search_cases`) populating `similar_prior_cases` with real, on-topic prior cases (e.g.
HHG-014 surfaced the actual ring cases from Phase 2; CC-0001 surfaced 3 genuinely similar card-not-present cases)
and those ids get written as real `SIMILAR_TO` edges in the graph (agent/memory.py) -- so both forms of memory
this system has (same-card structured history, and semantic vector retrieval) are demonstrated working, not just
one. Results: `outputs/memory_eval.json`.

## Phase 8: benchmark run - a real calibration bug found by looking at the OVERALL distribution, not one case

Ran the full 20-case benchmark twice before trusting it. Run 1 (after the Phase 5 gather_more fixes) came back
17 `fraud` / 3 `uncertain` / **0 `legitimate`** out of 20. README: "Half the cases are legitimate... An agent
that blocks everything scores badly." Zero legitimate verdicts across 20 real cases was a signal something was
still wrong, even though every individual case's reasoning looked locally defensible -- this only showed up by
looking at the aggregate, not by reviewing any single case file.

Root cause: `detectors/patterns.py`'s `PatternResult.confidence` answers "if this IS fraud, which pattern is it"
(validated at ~100% in Phase 2, but only ever tested against episodes ALREADY KNOWN to be confirmed fraud) --
NOT "is this fraud at all". `agent/uncertainty.assess()` was blending that confidence directly into
`fraud_probability`, but the channel-composition rules (`card_not_present_fraud`, `card_not_present_new_device`,
the in-person `account_takeover`/`out_of_region_use` soft calls) fire on the SHAPE of an episode alone -- "this
happened online", "this happened in person" -- which is true of essentially every transaction, fraud or not.
Those branches carried confidence 0.5-0.85 regardless of how mundane the transaction looked, so EVERY online
purchase started with an artificial floor around 0.25-0.35 just from pattern-matching, on top of whatever the
propensity model contributed -- collapsing the whole legitimate-leaning population toward "uncertain" at best,
never confidently "legitimate".

Fix: split `PatternResult` into `confidence` (unchanged, still "which pattern") and a new `evidence_strength`
("does matching this pattern indicate fraud at all"). Composition-only branches got LOW evidence_strength
(0.15-0.35: matching them alone is weak evidence), while the rare, separately-validated signals (structuring
0.85, a calibrated device ring, strict card-testing 0.85) kept HIGH evidence_strength, unchanged from before.
`agent/uncertainty.assess()` now blends propensity with `evidence_strength`, not `confidence`. `apply_memory_prior`
and the ATO/OOR alternative-picking logic still correctly use `confidence` (unaffected -- that's genuinely a
"which pattern" decision, not a "how suspicious" one).

Verified the fix on the same 5 spot-check cases before re-running all 20: HHG-001 and HHG-002 (previously
`uncertain` at 0.44/0.32) now correctly resolve to `legitimate` at 0.08/0.13 once a low-suspicion simulated
response confirms a weak underlying signal; HHG-009 (customer denial, strong pattern) still lands confidently
at 0.90; HHG-014 (the device ring) is unaffected at 0.86, exactly as it should be -- the fix only pulled down
the DEFAULT/composition-only floor, not the rare validated signals.

Final run (`scripts/60_run_benchmark.py`, all 20 case_pack cases, `cases/*.json`): see the console output logged
alongside this note and `outputs/benchmark_summary.json` for the exact verdict/pattern/SAR distribution. All 20
files pass `agent/validate.py`'s structural + ID-existence checks with 0 problems.

**Process note for anyone reading this later**: none of the three real bugs found in Phases 5 and 8 (the
`no reply` string mismatch, the step-up-auth binary-split bias, and this confidence/evidence_strength
conflation) were visible from reading the code in isolation. Each one only surfaced by actually running cases
and checking whether the AGGREGATE output made sense against a stated expectation (the README's "half
legitimate", the policy's own stop conditions) -- not by reviewing any single case's reasoning, which looked
locally fine every time.

### Final benchmark result (after all Phase 8 fixes)

```
HHG-001   legitimate  out_of_region_use            p=0.08 sar=False
HHG-002   legitimate  card_not_present_fraud       p=0.13 sar=False
HHG-003   fraud       out_of_region_use            p=0.71 sar=False
HHG-004   fraud       card_not_present_new_device  p=0.63 sar=False
HHG-005   legitimate  card_not_present_new_device  p=0.07 sar=False
HHG-006   fraud       undocumented                 p=0.92 sar=True   (structuring)
HHG-007   fraud       account_takeover             p=0.85 sar=False
HHG-008   fraud       card_testing                 p=0.86 sar=False
HHG-009   fraud       card_not_present_fraud       p=0.90 sar=False
HHG-010   legitimate  card_not_present_new_device  p=0.06 sar=False
HHG-011   fraud       card_not_present_new_device  p=0.80 sar=False
HHG-012   legitimate  out_of_region_use            p=0.12 sar=False
HHG-013   legitimate  card_not_present_new_device  p=0.09 sar=False
HHG-014   fraud       undocumented                 p=0.86 sar=True   (device ring, matches analyst's own tip)
HHG-015   legitimate  card_not_present_new_device  p=0.07 sar=False
HHG-016   fraud       card_not_present_new_device  p=0.80 sar=False
HHG-017   fraud       card_not_present_fraud       p=0.66 sar=False
HHG-018   fraud       account_takeover             p=0.73 sar=False
HHG-019   fraud       card_not_present_new_device  p=0.88 sar=False
HHG-020   legitimate  card_not_present_new_device  p=0.07 sar=False
```

**20/20 cases, 20/20 pass `agent/validate.py` (structural + ID-existence), 0 failures, 368s total runtime
(~18s/case average).** 8 legitimate / 12 fraud, 2 SAR filings (both on cases with a rare, calibrated signal --
undocumented structuring and the device ring -- not on a default composition match, exactly as R6/R9/policy
s.3a intend: "most cases never need a report"). No case landed on `uncertain` this run -- every case's
evidence-gathering loop resolved decisively one way or the other (a legitimate outcome of the design, not a
sign the loop is unused: `uncertain` is still fully supported and DID fire during earlier debugging runs on
these same cases, e.g. HHG-001/002 before their evidence requests resolved).

**Reproduce**: `scripts/60_run_benchmark.py` (idempotent, overwrites `cases/*.json`). Takes ~4 model-provider
calls' worth of latency variance per case (17-56s observed) depending on Gemini/NVIDIA response time and one
Savanna wake if the workspace had gone idle.
