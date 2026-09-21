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
