"""Validates one answer-file dict against outputs/ANSWER_FORMAT.md's structural requirements. Returns a list of
problems (empty = valid). Checks presence/type of every field, the enum fields' allowed values, the
verdict/pattern/sar consistency rules the format spells out, and that every ID referenced actually exists in
the dataset (README: "Made-up IDs score zero") -- checked against the local DuckDB mirror of the loaded data."""
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]

VERDICTS = {"fraud", "legitimate", "uncertain"}
STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
PATTERNS = {"card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use",
           "account_takeover", "undocumented", "none"}
SOURCES = {"graph", "document", "customer", "external"}
ROUTES = {"auto", "L1", "L2"}
ACTIONS = {"ALLOW_TRANSACTION", "DECLINE_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS", "WARN_CUSTOMER",
          "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH", "BLOCK_CARD", "BLOCK_ALL_CARDS", "GENERATE_REPORT", "CREATE_CASE",
          "FILE_REPORT", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"}
EV_REQ_TYPES = {"customer_validation", "step_up_auth", "analyst_info"}


class _IdSets:
    _instance = None

    def __init__(self):
        con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)
        self.txn_ids = {str(r[0]) for r in con.execute("SELECT TransactionID FROM transactions").fetchall()}
        self.card_ids = {r[0] for r in con.execute("SELECT card_id FROM card_map").fetchall()}
        self.customer_ids = {r[0] for r in con.execute("SELECT customer_id FROM transactions").fetchall()}
        self.cc_ids = {r[0] for r in con.execute("SELECT case_id FROM closed_cases").fetchall()}
        con.close()

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def validate(answer: dict) -> list:
    p = []
    ids = _IdSets.get()

    def req(cond, msg):
        if not cond:
            p.append(msg)

    req(isinstance(answer.get("case_id"), str) and answer["case_id"], "case_id missing/empty")
    for k in ("evidence_requests", "tool_calls", "tokens", "latency_s", "stop_reason", "case", "sar", "next_best_actions"):
        req(k in answer, f"top-level field missing: {k}")
    if any(k not in answer for k in ("case", "sar", "next_best_actions")):
        return p  # can't check nested structure without the parents

    c = answer["case"]
    req(c.get("status") in STATUSES, f"case.status invalid: {c.get('status')!r}")
    req(c.get("verdict") in VERDICTS, f"case.verdict invalid: {c.get('verdict')!r}")
    fp = c.get("fraud_probability")
    req(isinstance(fp, (int, float)) and 0 <= fp <= 1, f"case.fraud_probability out of range: {fp!r}")
    req(c.get("pattern") in PATTERNS, f"case.pattern invalid: {c.get('pattern')!r}")
    req(bool(c.get("pattern_description")) == (c.get("pattern") == "undocumented"),
       "pattern_description must be set iff pattern == 'undocumented'")
    req(isinstance(c.get("summary"), str) and c["summary"], "case.summary missing/empty")
    req(isinstance(c.get("written_to_graph"), bool), "case.written_to_graph must be bool")

    if c.get("verdict") == "legitimate":
        req(c.get("affected_txn_ids") == [], "legitimate verdict: affected_txn_ids must be empty")
        req(c.get("exposure_usd") == 0, "legitimate verdict: exposure_usd must be 0")

    for t in c.get("affected_txn_ids", []):
        req(str(t) in ids.txn_ids, f"affected_txn_ids has unknown txn id: {t}")
    for cid in c.get("connected_card_ids", []):
        req(cid in ids.card_ids, f"connected_card_ids has unknown card id: {cid}")
    for cc in c.get("similar_prior_cases", []):
        req(cc in ids.cc_ids, f"similar_prior_cases has unknown closed-case id: {cc}")
    for e in c.get("evidence", []):
        req(e.get("source") in SOURCES, f"evidence.source invalid: {e.get('source')!r}")
        req("claim" in e and "ref" in e and "entity_ids" in e, "evidence entry missing claim/ref/entity_ids")

    sar = answer["sar"]
    req(isinstance(sar.get("file"), bool), "sar.file must be bool")
    fires_in_final = any(a.get("action") == "FILE_REPORT" for a in answer["next_best_actions"].get("final", []))
    req(sar["file"] == fires_in_final, "sar.file must agree with whether FILE_REPORT is in next_best_actions.final")
    if sar["file"]:
        req(bool(sar.get("narrative")), "sar.narrative required when sar.file is true")
        req(len(sar.get("activity_dates", [])) == 2, "sar.activity_dates must have exactly 2 entries when filing")
    else:
        req(sar.get("narrative", "") == "", "sar.narrative must be empty when sar.file is false")
        req(sar.get("subjects", []) == [], "sar.subjects must be empty when sar.file is false")
        req(sar.get("total_amount_usd", 0) == 0, "sar.total_amount_usd must be 0 when sar.file is false")
        req(sar.get("activity_dates", []) == [], "sar.activity_dates must be empty when sar.file is false")

    for phase in ("initial", "final"):
        for a in answer["next_best_actions"].get(phase, []):
            req(a.get("action") in ACTIONS, f"next_best_actions.{phase} has unknown action: {a.get('action')!r}")
            req(a.get("route") in ROUTES, f"next_best_actions.{phase} has invalid route: {a.get('route')!r}")
            req(bool(a.get("reason")), f"next_best_actions.{phase} action {a.get('action')} missing reason")
    seen = [a["action"] for a in answer["next_best_actions"].get("final", [])]
    req(len(seen) == len(set(seen)), f"next_best_actions.final has duplicate actions: {seen}")

    for r in answer.get("evidence_requests", []):
        req(r.get("type") in EV_REQ_TYPES, f"evidence_requests.type invalid: {r.get('type')!r}")
        req(bool(r.get("assumed_response")), "evidence_requests entry missing assumed_response")

    return p
