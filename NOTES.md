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
