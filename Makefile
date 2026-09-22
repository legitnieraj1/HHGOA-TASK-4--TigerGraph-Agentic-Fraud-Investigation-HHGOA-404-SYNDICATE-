.PHONY: venv profile setup-graph export load verify-load install-queries train-propensity mcp-smoke seed-memory benchmark memory-eval api up

VENV := .venv/bin

venv:
	python3.11 -m venv .venv
	$(VENV)/pip install -q --upgrade pip
	$(VENV)/pip install -e .

profile:            ## Phase 0: schema/stats from the raw CSVs (DuckDB, never loads transactions.csv whole)
	$(VENV)/python scripts/00_profile.py

setup-graph:         ## Phase 1: create FraudGraph, apply schema + vector attributes on Savanna
	$(VENV)/python scripts/10_setup_graph.py

export:              ## Phase 1: DuckDB -> TSV files ready for TigerGraph loading jobs
	$(VENV)/python scripts/15_export.py

load:                ## Phase 1: chunked, checkpointed, idempotent load into FraudGraph
	$(VENV)/python scripts/20_load_data.py

verify-load:          ## Phase 1: reconcile graph vertex/edge counts against the export
	$(VENV)/python scripts/25_verify_load.py

build-features:       ## Phase 2: history-only graph features + closed-case join tables (DuckDB)
	$(VENV)/python scripts/30_build_features.py && $(VENV)/python scripts/31_graph_features.py

train-propensity:     ## Phase 2: fraud-propensity model (OOF-calibrated), scores every txn into local `pred` table
	$(VENV)/python scripts/32_train_propensity.py

install-queries:      ## Phase 2: create + install all tigergraph/queries/*.gsql, verify by name
	$(VENV)/python scripts/35_install_queries.py

mcp-smoke:            ## Phase 3: direct + LLM-tool-call checks against the MCP server (needs a live workspace)
	$(VENV)/python tests/test_mcp_direct_smoke.py
	$(VENV)/python tests/test_mcp_agent_smoke.py

up: venv profile setup-graph export load verify-load build-features train-propensity install-queries seed-memory  ## full pipeline, empty workspace -> ready graph
	@echo "Graph ready. Next: make mcp-smoke, make benchmark, make api."

seed-memory:          ## Phase 4: embed + upsert policy chunks and closed-case summaries as vectors
	$(VENV)/python scripts/40_seed_memory.py

memory-eval:           ## Phase 6: case-memory ablation (with vs without same-card history)
	$(VENV)/python scripts/45_memory_eval.py

benchmark:             ## Phase 8: run all 20 case_pack cases -> cases/*.json
	$(VENV)/python scripts/60_run_benchmark.py

api:                    ## Phase 7: serve the dashboard + API at http://127.0.0.1:8080
	$(VENV)/uvicorn api.main:app --port 8080
