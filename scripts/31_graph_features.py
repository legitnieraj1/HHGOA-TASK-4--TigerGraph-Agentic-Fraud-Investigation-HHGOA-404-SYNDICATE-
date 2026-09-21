"""Graph-derived, history-only features per txn (no future leakage): computed in DuckDB, mirrored by GSQL queries.
Table gfeat(txn, ...). All features use only rows with ts < this txn's ts (strictly earlier) on the same card/device."""
import pathlib
import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"))
con.execute("PRAGMA memory_limit='8GB'")
con.execute("DROP TABLE IF EXISTS gfeat")
con.execute("""CREATE TABLE gfeat AS
WITH ordered AS (
  SELECT txn, card_id, customer_id, ts, epoch(ts) e, amt, channel, product, addr1, device_key, p_email
  FROM tx),
w AS (
  SELECT txn, card_id, e, amt, channel, product, addr1, device_key,
    e - lag(e) OVER c AS prev_gap_s,
    count(*) OVER (PARTITION BY card_id ORDER BY e RANGE BETWEEN 3600 PRECEDING AND 1 PRECEDING) AS n_1h,
    count(*) OVER (PARTITION BY card_id ORDER BY e RANGE BETWEEN 86400 PRECEDING AND 1 PRECEDING) AS n_24h,
    count(*) FILTER (WHERE channel='online') OVER (PARTITION BY card_id ORDER BY e RANGE BETWEEN 3600 PRECEDING AND 1 PRECEDING) AS n_1h_online,
    avg(amt) OVER (PARTITION BY card_id ORDER BY e ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING) AS avg_amt_prev50,
    count(*) FILTER (WHERE amt < 5 AND channel='online') OVER (PARTITION BY card_id ORDER BY e RANGE BETWEEN 3600 PRECEDING AND 1 PRECEDING) AS n_small_1h,
    row_number() OVER (PARTITION BY card_id, device_key ORDER BY e) AS dev_rank_card,
    row_number() OVER (PARTITION BY card_id, addr1 ORDER BY e) AS reg_rank_card,
    row_number() OVER (PARTITION BY card_id, product ORDER BY e) AS prod_rank_card
  FROM ordered
  WINDOW c AS (PARTITION BY card_id ORDER BY e)),
devcards AS (  -- distinct OTHER cards that used this device strictly before
  SELECT a.txn, count(DISTINCT b.card_id) AS dev_other_cards_prior
  FROM (SELECT txn, card_id, device_key, e FROM ordered WHERE device_key IS NOT NULL) a
  JOIN (SELECT card_id, device_key, min(e) AS first_e FROM ordered WHERE device_key IS NOT NULL GROUP BY 1,2) b
    ON b.device_key = a.device_key AND b.card_id <> a.card_id AND b.first_e < a.e
  GROUP BY 1)
SELECT w.txn,
  coalesce(prev_gap_s, -1) AS g_prev_gap_s,
  n_1h AS g_n_1h, n_24h AS g_n_24h, coalesce(n_1h_online,0) AS g_n_1h_online, coalesce(n_small_1h,0) AS g_n_small_1h,
  CASE WHEN avg_amt_prev50 IS NULL OR avg_amt_prev50 = 0 THEN -1 ELSE amt / avg_amt_prev50 END AS g_amt_ratio,
  CASE WHEN device_key IS NULL THEN -1 WHEN dev_rank_card = 1 THEN 1 ELSE 0 END AS g_dev_new_card,
  CASE WHEN addr1 IS NULL THEN -1 WHEN reg_rank_card = 1 THEN 1 ELSE 0 END AS g_region_new_card,
  CASE WHEN prod_rank_card = 1 THEN 1 ELSE 0 END AS g_product_new_card,
  coalesce(dc.dev_other_cards_prior, 0) AS g_dev_other_cards
FROM w LEFT JOIN devcards dc USING (txn)""")
print(con.execute("SELECT count(*), avg((g_dev_new_card=1)::INT), avg((g_region_new_card=1)::INT), max(g_dev_other_cards) FROM gfeat").fetchone())
