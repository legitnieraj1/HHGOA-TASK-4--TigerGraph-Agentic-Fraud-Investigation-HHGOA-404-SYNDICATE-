"""Train the fraud-propensity model.
- OOF predictions for every Jul-Oct txn via 5-fold GroupKFold by customer (honest evaluation on closed cases).
- Final model on all Jul-Oct, applied to Nov-Dec (the case pack period). Isotonic calibration fitted on OOF.
Writes table `pred(txn, p_raw, p_cal, source)` into profile.duckdb and data/models/propensity.joblib."""
import pathlib
import sys
import time

import duckdb
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from detectors.propensity import encode, feature_cols, load_features  # noqa: E402

t0 = time.time()
lab = load_features("t.ts < '2016-11-03'")
lab, vocab = encode(lab)
FS = feature_cols(lab)
print(f"labelled {lab.shape}, pos {int(lab.y.sum())}, {len(FS)} features", flush=True)


def mk():
    return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08, max_leaf_nodes=48, l2_regularization=1.0, random_state=0)


oof = np.zeros(len(lab))
for k, (tr, te) in enumerate(GroupKFold(5).split(lab, lab.y, lab.customer_id)):
    m = mk().fit(lab.iloc[tr][FS], lab.iloc[tr].y)
    oof[te] = m.predict_proba(lab.iloc[te][FS])[:, 1]
    print(f"fold {k}: AUC {roc_auc_score(lab.iloc[te].y, oof[te]):.4f}  ({time.time()-t0:.0f}s)", flush=True)
print(f"OOF overall AUC {roc_auc_score(lab.y, oof):.4f}  AP {average_precision_score(lab.y, oof):.3f}")
iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(oof, lab.y)
final = mk().fit(lab[FS], lab.y)

new = load_features("t.ts >= '2016-11-03'")
new, _ = encode(new, vocab)
p_new = final.predict_proba(new[FS])[:, 1]
import pandas as pd
pred = pd.concat([
    pd.DataFrame({"txn": lab.txn, "p_raw": oof, "p_cal": iso.predict(oof), "source": "oof_jul_oct"}),
    pd.DataFrame({"txn": new.txn, "p_raw": p_new, "p_cal": iso.predict(p_new), "source": "final_nov_dec"})])
con = duckdb.connect(str(ROOT / "data" / "profile" / "profile.duckdb"))
con.execute("DROP TABLE IF EXISTS pred")
con.execute("CREATE TABLE pred AS SELECT * FROM pred")
joblib.dump({"model": final, "vocab": vocab, "features": FS, "iso": iso}, ROOT / "data" / "models" / "propensity.joblib")
print("pred rows", con.execute("SELECT count(*) FROM pred").fetchone(), f"total {time.time()-t0:.0f}s")
