"""Assembles the deterministic evidence bundle for one flagged transaction: graph facts (installed GSQL queries,
called through tigergraph.client.TG) + offline propensity scores (local `pred` table) + pattern classification.

This is what agent/nodes/gather_evidence.py hands to the LLM as SYNTHESISED context (never raw CSV rows).
No LLM call happens in this module -- it is the deterministic half the policy requires (NOTES.md, "don't let the
LLM do the fraud detection"). Every number here is traceable to a named query, matching the answer format's
`evidence[].source == "graph"` / `ref == "query:<name>(...)"` requirement."""
import pathlib
import duckdb

from tigergraph.client import TG
from detectors.patterns import classify, apply_memory_prior, PatternResult

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE_DB = ROOT / "data" / "profile" / "profile.duckdb"

EPISODE_HOURS = 24
EPISODE_P_MIN = 0.5
TESTING_HOURS = 168
TESTING_TINY = 5.0
TESTING_LARGE = 10.0
STRUCT_THRESHOLDS = (250.0, 500.0, 1000.0, 2000.0)
STRUCT_HOURS = 6
STRUCT_MINUTES = 60
BEHAVIOUR_LOOKBACK_DAYS = 180
NEIGHBOURHOOD_DAYS = 120
RING_DAYS = 120
REGION_DAYS = 30


def _flat(resp):
    if resp.get("error"):
        raise RuntimeError(resp.get("message"))
    o = {}
    for d in resp["results"]:
        o.update(d)
    return o


def _pred_scores(txn_ids):
    """Offline propensity scores for a set of txn ids, from the local pre-scored table (scripts/32_train_propensity.py).
    Not a TigerGraph call: cheap, deterministic, and already computed for all 590,742 txns."""
    if not txn_ids:
        return {}
    con = duckdb.connect(str(PROFILE_DB), read_only=True)
    ids = ",".join(str(int(x)) for x in txn_ids)
    rows = con.execute(f"SELECT txn, p_cal FROM pred WHERE txn IN ({ids})").fetchall()
    con.close()
    return dict(rows)


def build(tg: TG, txn_id: int, card_id: str, customer_id: str) -> dict:
    """Returns a dict: flagged_txn, episode (list of txns), pattern (PatternResult), evidence (list of
    {claim, source, ref, entity_ids} matching the answer format), and the raw bundles for debugging."""
    ev = []  # answer-format evidence entries, built up as each query runs

    flagged = _flat(tg.run_query("get_transaction", txn=str(txn_id)))
    if not flagged.get("Start"):
        raise ValueError(f"txn {txn_id} not found in graph")
    fa = flagged["Start"][0]["attributes"]
    ts, channel, addr1, device_key = fa["ts"], fa["channel"], fa["addr1"], None
    for link in flagged["links"]:
        if link.startswith("device|"):
            device_key = link.split("|", 1)[1]
    ev.append({"claim": f"Flagged transaction {txn_id}: ${fa['amount']:.2f} {fa['product_cd']} on {fa['channel']}, "
                        f"risk_score {fa['risk_score']:.2f}, {ts}", "source": "graph", "ref": "query:get_transaction",
              "entity_ids": [str(txn_id)]})

    # --- episode reconstruction: +-24h same-card window, propensity>=0.5 & same channel, calibrated F1 0.885 ---
    from datetime import datetime, timedelta
    t0 = (datetime.fromisoformat(ts) - timedelta(hours=EPISODE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    t1 = (datetime.fromisoformat(ts) + timedelta(hours=EPISODE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    window = _flat(tg.run_query("card_window", card=card_id, t_from=t0, t_to=t1))["T"]
    window = [w["attributes"] for w in window]
    scores = _pred_scores([w["txn"] for w in window])
    episode = [w for w in window if w["txn"] == txn_id or (scores.get(w["txn"], 0) >= EPISODE_P_MIN and w["channel"] == channel)]
    if not any(w["txn"] == txn_id for w in episode):
        episode.append(next(w for w in window if w["txn"] == txn_id))
    ev.append({"claim": f"Episode reconstruction: {len(episode)} of {len(window)} transactions on {card_id} within "
                        f"+-{EPISODE_HOURS}h scored >= {EPISODE_P_MIN} fraud-propensity on the same channel",
              "source": "graph", "ref": f"query:card_window(card={card_id},+-{EPISODE_HOURS}h)+offline_propensity",
              "entity_ids": [str(w["txn"]) for w in episode]})

    # --- pattern-specific probes (only where relevant: online episodes for testing/structuring, any for ring) ---
    testing = structuring = ring = None
    if channel == "online":
        testing = _flat(tg.run_query("pattern_card_testing", card=card_id, t_ref=ts, hours=TESTING_HOURS,
                                     tiny_amt=TESTING_TINY, large_amt=TESTING_LARGE))
        if testing.get("strict_match") or testing.get("loose_match"):
            ev.append({"claim": f"Card-testing probe: {testing['max_tiny_in_60min']} tiny (<${TESTING_TINY:.0f}) online "
                                f"auths within 60 min ({testing['n_tiny_in_window']} in +-{TESTING_HOURS}h), "
                                f"strict={testing['strict_match']}", "source": "graph",
                      "ref": f"query:pattern_card_testing(card={card_id})",
                      "entity_ids": [str(x) for x in testing["tiny_run_txns"] + testing["larger_purchases_after"]]})
        for T in STRUCT_THRESHOLDS:
            structuring = _flat(tg.run_query("pattern_structuring", card=card_id, t_ref=ts, hours=STRUCT_HOURS,
                                             threshold=T, minutes=STRUCT_MINUTES))
            if structuring.get("match"):
                ev.append({"claim": f"Structuring probe: {structuring['max_in_window']} online purchases just under "
                                    f"${T:,.0f} within {STRUCT_MINUTES} min, total ${structuring['run_total']:,.2f}",
                          "source": "graph", "ref": f"query:pattern_structuring(card={card_id},threshold={T})",
                          "entity_ids": [str(x) for x in structuring["run_txns"]]})
                break
        else:
            structuring = None
    if device_key:
        ring = _flat(tg.run_query("pattern_device_ring", device=device_key, asof=ts, days=RING_DAYS))
        if (ring.get("n_cards") or 0) >= 3:
            ev.append({"claim": f"Device-ring probe: device profile seen on {ring['n_cards']} distinct cards, "
                                f"{ring['n_txns']} transactions, in the last {RING_DAYS} days ({ring.get('proxy_counts')}, "
                                f"{ring.get('dev_status_counts')})", "source": "graph",
                      "ref": f"query:pattern_device_ring(device={device_key!r},days={RING_DAYS})",
                      "entity_ids": list((ring.get("fraud_linked_cards") or []))})

    # --- baselines + memory (customer_profile carries prior closed cases, most-recent-first) ---
    behaviour = _flat(tg.run_query("card_behaviour", card=card_id, asof=ts, lookback_days=BEHAVIOUR_LOOKBACK_DAYS))
    profile = _flat(tg.run_query("customer_profile", customer=customer_id, asof=ts))
    neighbourhood = _flat(tg.run_query("card_neighbourhood", card=card_id, asof=ts, days=NEIGHBOURHOOD_DAYS))
    region = None
    if channel == "in_person" and addr1 and addr1 >= 0:
        region = _flat(tg.run_query("region_cluster", region=str(addr1), asof=ts, days=REGION_DAYS))

    prior_cases = [line.split("|") for line in profile.get("prior_closed_cases", [])]
    prior_fraud_patterns = [p[3] for p in prior_cases if len(p) >= 5 and p[2] == "confirmed_fraud"]
    similar_prior_cases = [p[0] for p in prior_cases if len(p) >= 5 and p[2] == "confirmed_fraud"][:5]
    if prior_cases:
        ev.append({"claim": f"Case memory: {len(prior_cases)} prior closed case(s) on this customer's cards, most recent "
                            f"{prior_cases[0][3]} ({prior_cases[0][2]}) opened {prior_cases[0][5] if len(prior_cases[0]) > 5 else '?'}",
                  "source": "graph", "ref": f"query:customer_profile(customer={customer_id})",
                  "entity_ids": [p[0] for p in prior_cases[:5]]})

    # NOTE: raw card_neighbourhood "other cards on a shared device with a fraud history" is NOT used as evidence.
    # 10.1% of all 14,317 cards have >=1 confirmed-fraud closed case (base rate; NOTES.md), so on a popular device
    # (hundreds of users) that count is large by chance alone -- citing it would be an unsupported claim (policy s.7,
    # "every claim must be traceable to evidence"). Only the ring_strength() calibrated signal (device New + proxied
    # on ~all its activity; 0 false positives across 25 closed-case negatives, NOTES.md) counts as a device link.
    fraud_linked_from_devices = set(ring.get("fraud_linked_cards") or []) if ring and (ring.get("n_cards") or 0) >= 3 else set()

    # --- pattern classification (deterministic; LLM never computes this) ---
    pat = classify(episode, structuring=structuring, testing=testing, ring=ring)
    pat = apply_memory_prior(pat, prior_fraud_patterns)

    return {
        "flagged_txn": fa, "ts": ts, "channel": channel, "device_key": device_key, "addr1": addr1,
        "episode": episode, "episode_txn_ids": [w["txn"] for w in episode],
        "testing": testing, "structuring": structuring, "ring": ring,
        "behaviour": behaviour, "profile": profile, "neighbourhood": neighbourhood, "region": region,
        "prior_fraud_patterns": prior_fraud_patterns, "similar_prior_cases": similar_prior_cases,
        "fraud_linked_connected_cards": sorted(fraud_linked_from_devices),
        "pattern": pat, "evidence": ev,
    }
