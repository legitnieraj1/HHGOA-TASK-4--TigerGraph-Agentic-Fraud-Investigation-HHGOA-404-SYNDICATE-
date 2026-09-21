"""Phase 0 profiling. DuckDB streams the CSVs; transactions.csv is never loaded whole into RAM.

Writes data/profile/profile.json and a local profile.duckdb (git-ignored). Re-runnable (overwrites)."""
import json
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "profile"
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "transactions": RAW / "transactions.csv",
    "identity": RAW / "identity.csv",
    "closed_cases": RAW / "closed_cases_history.csv",
    "case_pack": RAW / "case_pack.csv",
}


def rel(name):
    # sample_size=-1: scan whole file for type inference (V/id columns have late-appearing values)
    return f"read_csv_auto('{FILES[name]}', header=true, sample_size=-1)"


db_path = OUT / "profile.duckdb"
db_path.unlink(missing_ok=True)
con = duckdb.connect(str(db_path))
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA threads=4")

profile = {}
for name in FILES:
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM {rel(name)}")
    cols = con.execute(f"DESCRIBE {name}").fetchall()
    n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    profile[name] = {"rows": n, "n_cols": len(cols), "columns": {c[0]: c[1] for c in cols}}
    print(name, n, "rows", len(cols), "cols", flush=True)


def one(sql):
    return con.execute(sql).fetchone()


def many(sql):
    return [list(r) for r in con.execute(sql).fetchall()]


tcols = list(profile["transactions"]["columns"])
non_v = [c for c in tcols if not (c.startswith("V") and c[1:].isdigit())]
v_cols = [c for c in tcols if c not in non_v]
sel = ", ".join(f'avg(CASE WHEN "{c}" IS NULL THEN 1.0 ELSE 0.0 END)' for c in non_v)
profile["transactions"]["null_rate_non_v"] = dict(zip(non_v, one(f"SELECT {sel} FROM transactions")))
vsel = ", ".join(f'avg(CASE WHEN "{c}" IS NULL THEN 1.0 ELSE 0.0 END)' for c in v_cols)
vn = one(f"SELECT {vsel} FROM transactions")
profile["transactions"]["null_rate_v_min_mean_max"] = [min(vn), sum(vn) / len(vn), max(vn)]

icols = list(profile["identity"]["columns"])
isel = ", ".join(f'avg(CASE WHEN "{c}" IS NULL THEN 1.0 ELSE 0.0 END)' for c in icols)
profile["identity"]["null_rate"] = dict(zip(icols, one(f"SELECT {isel} FROM identity")))

keys = {
    "customers": one("SELECT count(DISTINCT customer_id) FROM transactions")[0],
    "transaction_ids_distinct": one("SELECT count(DISTINCT TransactionID) FROM transactions")[0],
    "identity_txn_ids_distinct": one("SELECT count(DISTINCT TransactionID) FROM identity")[0],
    "identity_rows_matching_transactions": one(
        "SELECT count(*) FROM identity SEMI JOIN transactions USING (TransactionID)")[0],
    "card1_distinct": one("SELECT count(DISTINCT card1) FROM transactions")[0],
    "addr1_distinct": one("SELECT count(DISTINCT addr1) FROM transactions")[0],
    "p_email_distinct": one("SELECT count(DISTINCT P_emaildomain) FROM transactions")[0],
    "r_email_distinct": one("SELECT count(DISTINCT R_emaildomain) FROM transactions")[0],
    "deviceinfo_distinct": one("SELECT count(DISTINCT DeviceInfo) FROM identity")[0],
    "ts_min_max": [str(x) for x in one("SELECT min(ts), max(ts) FROM transactions")],
    "channel_counts": dict(many("SELECT channel, count(*) FROM transactions GROUP BY 1")),
    "productcd_x_channel": many("SELECT ProductCD, channel, count(*) FROM transactions GROUP BY 1,2 ORDER BY 1,2"),
    "channel_has_identity": many(
        "SELECT t.channel, count(*) total, count(i.TransactionID) has_identity FROM transactions t "
        "LEFT JOIN identity i USING (TransactionID) GROUP BY 1"),
    "cards_per_customer_hist": many(
        "WITH x AS (SELECT customer_id, count(DISTINCT card1) k FROM transactions GROUP BY 1) "
        "SELECT k, count(*) FROM x GROUP BY 1 ORDER BY 1"),
    "monthly_txns": many("SELECT strftime(ts,'%Y-%m') m, count(*) FROM transactions GROUP BY 1 ORDER BY 1"),
}
profile["keys"] = keys

rs = one("SELECT min(risk_score), quantile_cont(risk_score,0.5), quantile_cont(risk_score,0.9), "
         "quantile_cont(risk_score,0.99), max(risk_score), avg(risk_score) FROM transactions")
profile["risk_score"] = {
    "min_med_p90_p99_max_mean": list(rs),
    "hist_0.1": many("SELECT floor(risk_score*10)/10 b, count(*) FROM transactions GROUP BY 1 ORDER BY 1"),
}

profile["closed_cases_summary"] = {
    "outcome_x_pattern": many(
        "SELECT outcome, pattern, count(*), round(avg(n_txns),2), round(avg(exposure_usd),2) "
        "FROM closed_cases GROUP BY 1,2 ORDER BY 1,3 DESC"),
    "report_filed": many(
        "SELECT outcome, pattern, report_filed, count(*) FROM closed_cases GROUP BY 1,2,3 ORDER BY 1,2,3"),
    "opened_range": [str(x) for x in one("SELECT min(opened_at), max(opened_at) FROM closed_cases")],
}

(OUT / "profile.json").write_text(json.dumps(profile, indent=2, default=str))
print("wrote", OUT / "profile.json")
