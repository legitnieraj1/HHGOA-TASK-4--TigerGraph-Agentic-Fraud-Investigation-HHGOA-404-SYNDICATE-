"""Single source of truth for the graph: column specs drive (a) DuckDB export SQL, (b) GSQL vertex DDL, (c) loading jobs.

Missing numeric values are exported as the sentinel -1 (never 0), missing strings as "". Consumers must treat -1 as NULL."""

SEP = "\t"

# (attr, gsql_type, duckdb_expr over table `t` = transactions LEFT JOIN identity `i` LEFT JOIN card_map `cm`)
def _num(col, typ="DOUBLE"):
    return (col.lower(), typ, f"coalesce(t.{col}, -1)")

def _str(alias, expr):
    return (alias, "STRING", f"coalesce(cast({expr} AS VARCHAR), '')")

TXN_ATTRS = [
    ("ts", "DATETIME", "strftime(t.ts, '%Y-%m-%d %H:%M:%S')"),
    ("dt", "INT", "t.TransactionDT"),
    ("amount", "DOUBLE", "t.TransactionAmt"),
    _str("product_cd", "t.ProductCD"),
    _str("channel", "t.channel"),
    ("risk_score", "DOUBLE", "t.risk_score"),
    ("risk_tier", "STRING", "CASE WHEN t.risk_score >= 0.7 THEN 'high' WHEN t.risk_score >= 0.4 THEN 'medium' ELSE 'low' END"),
    ("card_id", "STRING", "cm.card_id"),
    ("customer_id", "STRING", "t.customer_id"),
    ("addr1", "INT", "coalesce(cast(t.addr1 AS INT), -1)"),
    ("addr2", "INT", "coalesce(cast(t.addr2 AS INT), -1)"),
    _num("dist1"), _num("dist2"),
    ("card2", "INT", "coalesce(cast(t.card2 AS INT), -1)"),
    ("card3", "INT", "coalesce(cast(t.card3 AS INT), -1)"),
    ("card5", "INT", "coalesce(cast(t.card5 AS INT), -1)"),
    _str("p_email", "t.P_emaildomain"),
    _str("r_email", "t.R_emaildomain"),
    *[_num(f"C{n}") for n in range(1, 15)],
    *[_num(f"D{n}") for n in range(1, 16)],
    *[_str(f"m{n}", f"t.M{n}") for n in range(1, 10)],
    ("has_identity", "BOOL", "CASE WHEN i.TransactionID IS NULL THEN 'false' ELSE 'true' END"),
    _str("device_type", "i.DeviceType"),
    _str("dev_status", "i.id_15"),      # New / Found / Unknown (README: id_15)
    _str("ip_proxy", "i.id_23"),           # transparent / anonymous / hidden (README: id_23)
    _str("id_12", "i.id_12"), _str("id_34", "i.id_34"),
    *[(f"id_{n:02d}", "DOUBLE", f"coalesce(i.id_{n:02d}, -1)") for n in range(1, 12)],
]

# Non-attribute columns appended to the txn export, used only by edge loads
DEVICE_KEY = ("coalesce(i.DeviceInfo,'') || ' | ' || coalesce(i.id_30,'') || ' | ' || coalesce(i.id_31,'') || ' | ' || coalesce(i.id_33,'')")
TXN_EDGE_COLS = [
    ("device_key", f"CASE WHEN i.TransactionID IS NULL OR (i.DeviceInfo IS NULL AND i.id_30 IS NULL AND i.id_31 IS NULL AND i.id_33 IS NULL) THEN '' ELSE {DEVICE_KEY} END"),
    ("region", "coalesce(cast(cast(t.addr1 AS INT) AS VARCHAR), '')"),
]

VERTICES = {
    "Customer": ("customer_id STRING", [("n_cards", "INT")]),
    "Card": ("card_id STRING", [("customer_id", "STRING"), ("network", "STRING"), ("card_type", "STRING"), ("k", "INT")]),
    "Transaction": ("txn_id INT", [(a, t) for a, t, _ in TXN_ATTRS]),
    "DeviceProfile": ("device_key STRING", [("device_info", "STRING"), ("os", "STRING"), ("browser", "STRING"),
                                             ("screen", "STRING"), ("device_type", "STRING")]),
    "EmailDomain": ("domain STRING", []),
    "BillingRegion": ("region STRING", []),
    "ClosedCase": ("case_id STRING", [("customer_id", "STRING"), ("card_id", "STRING"), ("opened_at", "DATETIME"),
                                       ("closed_at", "DATETIME"), ("outcome", "STRING"), ("pattern", "STRING"),
                                       ("first_fraud_txn_id", "INT"), ("n_txns", "INT"), ("exposure_usd", "DOUBLE"),
                                       ("actions_taken", "STRING"), ("report_filed", "BOOL"), ("analyst_notes", "STRING")]),
    # written by the agent (memory)
    "InvestigationCase": ("case_id STRING", [("trigger_type", "STRING"), ("status", "STRING"), ("verdict", "STRING"),
                                              ("pattern", "STRING"), ("fraud_probability", "DOUBLE"), ("exposure_usd", "DOUBLE"),
                                              ("opened_at", "DATETIME"), ("summary", "STRING"), ("answer_json", "STRING")]),
    "Action": ("action_id STRING", [("action", "STRING"), ("route", "STRING"), ("phase", "STRING"), ("reason", "STRING"),
                                     ("status", "STRING")]),
    "PolicyDoc": ("chunk_id STRING", [("source", "STRING"), ("section", "STRING"), ("title", "STRING"), ("text", "STRING")]),
}

# (name, from, to, attrs, reverse)
EDGES = [
    ("OWNS", "Customer", "Card", [], "rev_OWNS"),
    ("MADE", "Card", "Transaction", [], "rev_MADE"),
    ("FROM_DEVICE", "Transaction", "DeviceProfile", [], "rev_FROM_DEVICE"),
    ("PURCHASER_EMAIL", "Transaction", "EmailDomain", [], "rev_PURCHASER_EMAIL"),
    ("RECIPIENT_EMAIL", "Transaction", "EmailDomain", [], "rev_RECIPIENT_EMAIL"),
    ("BILLED_IN", "Transaction", "BillingRegion", [], "rev_BILLED_IN"),
    ("NEXT", "Transaction", "Transaction", [("gap_s", "INT")], "rev_NEXT"),
    ("INVOLVES", "ClosedCase", "Transaction", [], "rev_INVOLVES"),
    ("CC_ON_CARD", "ClosedCase", "Card", [], "rev_CC_ON_CARD"),
    ("CC_CONNECTED_TO", "ClosedCase", "Card", [], "rev_CC_CONNECTED_TO"),
    ("HAS_EVIDENCE", "InvestigationCase", "Transaction", [("claim", "STRING")], "rev_HAS_EVIDENCE"),
    ("CASE_ON_CARD", "InvestigationCase", "Card", [], "rev_CASE_ON_CARD"),
    ("CASE_CONNECTED_TO", "InvestigationCase", "Card", [], "rev_CASE_CONNECTED_TO"),
    ("CASE_DEVICE", "InvestigationCase", "DeviceProfile", [], "rev_CASE_DEVICE"),
    ("TOOK_ACTION", "InvestigationCase", "Action", [], "rev_TOOK_ACTION"),
    ("SIMILAR_TO", "InvestigationCase", "ClosedCase", [("score", "DOUBLE")], "rev_SIMILAR_TO"),
]

EMB_DIM = 384  # BAAI/bge-small-en-v1.5 / all-MiniLM-L6-v2
VECTORS = [("ClosedCase", "emb"), ("PolicyDoc", "emb"), ("InvestigationCase", "emb")]


def vertex_ddl(name):
    pid, attrs = VERTICES[name]
    cols = ", ".join([f"PRIMARY_ID {pid}"] + [f"{a} {t}" for a, t in attrs])
    return f"ADD VERTEX {name}({cols}) WITH primary_id_as_attribute=\"true\";"


def edge_ddl(e):
    name, fr, to, attrs, rev = e
    cols = ", ".join([f"FROM {fr}", f"TO {to}"] + [f"{a} {t}" for a, t in attrs])
    return f"ADD DIRECTED EDGE {name}({cols}) WITH REVERSE_EDGE=\"{rev}\";"


def schema_job(graph):
    body = "\n  ".join([vertex_ddl(v) for v in VERTICES] + [edge_ddl(e) for e in EDGES])
    return f"CREATE SCHEMA_CHANGE JOB fg_schema FOR GRAPH {graph} {{\n  {body}\n}}\nRUN SCHEMA_CHANGE JOB fg_schema\n"


def vector_job(graph):
    body = "\n  ".join(f'ALTER VERTEX {v} ADD VECTOR ATTRIBUTE {a}(DIMENSION={EMB_DIM}, METRIC="COSINE");' for v, a in VECTORS)
    return f"CREATE SCHEMA_CHANGE JOB fg_vectors FOR GRAPH {graph} {{\n  {body}\n}}\nRUN SCHEMA_CHANGE JOB fg_vectors\n"
