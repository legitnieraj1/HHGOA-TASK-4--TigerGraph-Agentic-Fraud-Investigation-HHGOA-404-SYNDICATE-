"""Export graph-ready TSVs from the profiled DuckDB (no header, tab separated, no quoting). Re-runnable (overwrites).

Card ids are DERIVED (see NOTES.md): customer_id-K{dense_rank(card6 asc, nulls first)}."""
import pathlib
import sys

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigergraph import spec  # noqa: E402

OUT = ROOT / "data" / "export"
OUT.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"), read_only=True)
con.execute("PRAGMA memory_limit='6GB'")


def clean(expr):  # keep TSV parseable
    return f"replace(replace(replace(coalesce(cast({expr} AS VARCHAR),''), chr(9), ' '), chr(10), ' '), chr(13), ' ')"


def copy(name, select):
    path = OUT / f"{name}.tsv"
    con.execute(f"COPY ({select}) TO '{path}' (DELIMITER '\t', HEADER false, QUOTE '', ESCAPE '')")
    n = con.execute(f"SELECT count(*) FROM ({select})").fetchone()[0]
    print(f"{name:14s} {n:>9,d} rows -> {path.name}", flush=True)
    return n


con.execute("""CREATE TEMP TABLE card_map AS
  SELECT customer_id, card6,
         customer_id || '-K' || cast(dense_rank() OVER (PARTITION BY customer_id ORDER BY card6 ASC NULLS FIRST) AS VARCHAR) AS card_id,
         cast(dense_rank() OVER (PARTITION BY customer_id ORDER BY card6 ASC NULLS FIRST) AS INT) AS k,
         any_value(card4) FILTER (WHERE card4 IS NOT NULL) AS network
  FROM transactions GROUP BY customer_id, card6""")

copy("customers", "SELECT customer_id, count(*) FROM card_map GROUP BY 1 ORDER BY 1")
copy("cards", f"SELECT card_id, customer_id, {clean('network')}, {clean('card6')}, k FROM card_map ORDER BY 1")

attrs = ", ".join(clean(e) if t in ("STRING",) else f"cast({e} AS VARCHAR)" for _, t, e in spec.TXN_ATTRS)
edge_cols = ", ".join(clean(e) for _, e in spec.TXN_EDGE_COLS)
txn_sql = f"""SELECT t.TransactionID, {attrs}, {edge_cols}
  FROM transactions t
  LEFT JOIN identity i ON i.TransactionID = t.TransactionID
  JOIN card_map cm ON cm.customer_id = t.customer_id AND cm.card6 IS NOT DISTINCT FROM t.card6
  ORDER BY t.TransactionID"""
n_txn = copy("txns", txn_sql)
assert n_txn == 590742, n_txn  # join must not drop or duplicate

copy("next", """SELECT t.TransactionID, lead(t.TransactionID) OVER w, lead(t.TransactionDT) OVER w - t.TransactionDT
  FROM transactions t JOIN card_map cm ON cm.customer_id = t.customer_id AND cm.card6 IS NOT DISTINCT FROM t.card6
  WINDOW w AS (PARTITION BY cm.card_id ORDER BY t.TransactionDT, t.TransactionID)
  QUALIFY lead(t.TransactionID) OVER w IS NOT NULL""")

dev = f"coalesce(DeviceInfo,'') || ' | ' || coalesce(id_30,'') || ' | ' || coalesce(id_31,'') || ' | ' || coalesce(id_33,'')"
copy("devices", f"""SELECT {clean(dev)}, {clean('DeviceInfo')}, {clean('id_30')}, {clean('id_31')}, {clean('id_33')}, {clean('any_value(DeviceType)')}
  FROM identity WHERE NOT (DeviceInfo IS NULL AND id_30 IS NULL AND id_31 IS NULL AND id_33 IS NULL)
  GROUP BY DeviceInfo, id_30, id_31, id_33 ORDER BY 1""")
copy("emails", "SELECT d FROM (SELECT P_emaildomain d FROM transactions UNION SELECT R_emaildomain FROM transactions) WHERE d IS NOT NULL ORDER BY 1")
copy("regions", "SELECT DISTINCT cast(cast(addr1 AS INT) AS VARCHAR) FROM transactions WHERE addr1 IS NOT NULL ORDER BY 1")

copy("closed_cases", f"""SELECT case_id, customer_id, card_id, strftime(opened_at,'%Y-%m-%d %H:%M:%S'), strftime(closed_at,'%Y-%m-%d %H:%M:%S'),
  outcome, pattern, coalesce(first_fraud_txn_id, -1), n_txns, exposure_usd, {clean('actions_taken')}, cast(report_filed AS VARCHAR), {clean('analyst_notes')}
  FROM closed_cases ORDER BY case_id""")
copy("involves", "SELECT case_id, unnest(string_split(txn_ids,'|')) FROM closed_cases ORDER BY 1")
copy("cc_connected", "SELECT case_id, unnest(string_split(connected_card_ids,'|')) FROM closed_cases WHERE connected_card_ids IS NOT NULL AND connected_card_ids<>'' ORDER BY 1")

# --- referential checks: every edge endpoint must exist ---
def chk(label, sql):
    bad = con.execute(sql).fetchone()[0]
    print(f"check {label}: {bad} orphan(s)")
    assert bad == 0, label

cm = "SELECT card_id FROM card_map"
chk("closed_cases.card_id", f"SELECT count(*) FROM closed_cases WHERE card_id NOT IN ({cm})")
chk("closed_cases.txn", "SELECT count(*) FROM (SELECT unnest(string_split(txn_ids,'|'))::BIGINT t FROM closed_cases) WHERE t NOT IN (SELECT TransactionID FROM transactions)")
chk("closed_cases.connected", f"SELECT count(*) FROM (SELECT unnest(string_split(connected_card_ids,'|')) c FROM closed_cases WHERE connected_card_ids<>'') WHERE c NOT IN ({cm})")
chk("case_pack.card", f"SELECT count(*) FROM case_pack WHERE card_id NOT IN ({cm})")
print("export ok:", sum(p.stat().st_size for p in OUT.glob('*.tsv')) // 1_000_000, "MB")
