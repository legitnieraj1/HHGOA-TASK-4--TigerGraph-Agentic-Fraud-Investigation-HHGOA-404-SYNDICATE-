"""Fraud-propensity scorer: gradient boosting over (a) Vesta features (C/D/M/V/id, unnamed) and (b) history-only graph features.

Trained ONLY on the provided closed cases: label 1 = txn in a confirmed_fraud case, label 0 = every other Jul-Oct txn
(incl. cleared alerts). Never uses the public Kaggle IEEE-CIS files. Output is a SIGNAL; the LLM never computes it."""
import pathlib

import duckdb
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "profile" / "profile.duckdb"
CAT = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain", "channel", "M4", "id_15", "id_23", "id_12", "id_34", "DeviceType"]


def load_features(where="TRUE", con=None):
    """One row per txn: feature columns + ids/ts/label. Categorical -> stable integer codes via fixed vocab."""
    own = con is None
    con = con or duckdb.connect(str(DB), read_only=True)
    con.execute("PRAGMA memory_limit='8GB'")
    cols = con.execute("DESCRIBE transactions").fetchall()
    num = [n for n, t, *_ in cols if t in ("DOUBLE", "BIGINT", "INTEGER") and n not in ("TransactionID", "customer_id", "card1", "TransactionDT")]
    boo = [n for n, t, *_ in cols if t == "BOOLEAN"]
    sel = ", ".join([f't."{n}"' for n in num] + [f'cast(t."{n}" AS DOUBLE) AS "{n}"' for n in boo]
                    + ['t."ProductCD"', 't."card4"', 't."card6"', 't."P_emaildomain"', 't."R_emaildomain"', 't."channel"', 't."M4"'])
    df = con.execute(f"""SELECT t.TransactionID AS txn, t.ts, x.card_id, x.customer_id, {sel},
        i.id_15, i.id_23, i.id_12, i.id_34, i.DeviceType, g.*  EXCLUDE (txn),
        coalesce(f.lbl, 0) AS y
      FROM transactions t
      JOIN tx x ON x.txn = t.TransactionID
      JOIN gfeat g ON g.txn = t.TransactionID
      LEFT JOIN identity i ON i.TransactionID = t.TransactionID
      LEFT JOIN (SELECT DISTINCT txn, 1 AS lbl FROM cc_txn WHERE outcome='confirmed_fraud') f ON f.txn = t.TransactionID
      WHERE {where}""").df()
    if own:
        con.close()
    df["hour"] = pd.to_datetime(df.ts).dt.hour
    return df


def encode(df, vocab=None):
    df = df.copy()
    vocab = vocab or {}
    for k in CAT:
        if k not in vocab:
            vocab[k] = {v: i for i, v in enumerate(sorted(df[k].dropna().astype(str).unique()))}
        df[k] = df[k].astype("object").map(lambda v, m=vocab[k]: m.get(str(v), -1) if v is not None and v == v else -1)
    return df, vocab


def feature_cols(df, use_risk=True, use_graph=True):
    drop = {"txn", "ts", "y", "card_id", "customer_id"}
    cols = [c for c in df.columns if c not in drop]
    if not use_risk:
        cols = [c for c in cols if c != "risk_score"]
    if not use_graph:
        cols = [c for c in cols if not c.startswith("g_")]
    return cols
