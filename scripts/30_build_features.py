"""Build `tx` (enriched, card-keyed transactions) and `cc_txn` (closed-case txn links) in profile.duckdb for calibration.
Same derivations as the graph export (card_id rule in NOTES.md)."""
import pathlib
import sys
import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tigergraph import spec  # noqa: E402

con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"))
con.execute("PRAGMA memory_limit='6GB'")
con.execute("DROP TABLE IF EXISTS card_map")
con.execute("""CREATE TABLE card_map AS
  SELECT customer_id, card6,
         customer_id || '-K' || cast(dense_rank() OVER (PARTITION BY customer_id ORDER BY card6 ASC NULLS FIRST) AS VARCHAR) AS card_id
  FROM transactions GROUP BY customer_id, card6""")
con.execute("DROP TABLE IF EXISTS tx")
con.execute(f"""CREATE TABLE tx AS
  SELECT t.TransactionID AS txn, t.customer_id, cm.card_id, t.ts, t.TransactionDT AS dt, t.TransactionAmt AS amt,
         t.ProductCD AS product, t.channel, t.risk_score AS risk, cast(t.addr1 AS INT) AS addr1, cast(t.addr2 AS INT) AS addr2,
         t.P_emaildomain AS p_email, t.R_emaildomain AS r_email,
         t.M1,t.M2,t.M3,t.M4,t.M5,t.M6,t.M7,t.M8,t.M9,
         i.id_15 AS dev_status, i.id_23 AS ip_proxy, i.DeviceType AS device_type,
         CASE WHEN i.TransactionID IS NULL OR (i.DeviceInfo IS NULL AND i.id_30 IS NULL AND i.id_31 IS NULL AND i.id_33 IS NULL) THEN NULL
              ELSE {spec.DEVICE_KEY} END AS device_key,
         i.TransactionID IS NOT NULL AS has_identity
  FROM transactions t
  LEFT JOIN identity i ON i.TransactionID = t.TransactionID
  JOIN card_map cm ON cm.customer_id = t.customer_id AND cm.card6 IS NOT DISTINCT FROM t.card6""")
con.execute("CREATE INDEX IF NOT EXISTS tx_card ON tx(card_id)")
con.execute("DROP TABLE IF EXISTS cc_txn")
con.execute("""CREATE TABLE cc_txn AS
  SELECT c.case_id, c.customer_id, c.card_id, c.outcome, c.pattern, c.opened_at, c.first_fraud_txn_id,
         cast(u.tid AS BIGINT) AS txn, u.pos
  FROM closed_cases c, LATERAL (SELECT unnest(string_split(c.txn_ids,'|')) AS tid, generate_subscripts(string_split(c.txn_ids,'|'),1) AS pos) u""")
print(con.execute("SELECT count(*) FROM tx").fetchone(), con.execute("SELECT count(*) FROM cc_txn").fetchone())
