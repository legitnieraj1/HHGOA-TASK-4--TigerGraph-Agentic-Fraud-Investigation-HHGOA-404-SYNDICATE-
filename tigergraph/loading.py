"""Generate GSQL loading jobs from spec.py. One file placeholder per job. Column positions come from spec order."""
from . import spec

OPTS = 'USING SEPARATOR="\\t", HEADER="false", EOL="\\n"'
N = len(spec.TXN_ATTRS)
IDX = {a: i + 1 for i, (a, _, _) in enumerate(spec.TXN_ATTRS)}   # $0 = txn id
IDX_DEVICE_KEY = N + 1
IDX_REGION = N + 2


def _vals(n):
    return ", ".join(f"${i}" for i in range(n))


def jobs(graph):
    J = {}
    J["customers"] = [f"LOAD f TO VERTEX Customer VALUES ({_vals(2)}) {OPTS};"]
    J["cards"] = [f"LOAD f TO VERTEX Card VALUES ({_vals(5)}) {OPTS};",
                  f"LOAD f TO EDGE OWNS VALUES ($1, $0) {OPTS};"]
    J["devices"] = [f"LOAD f TO VERTEX DeviceProfile VALUES ({_vals(6)}) {OPTS};"]
    J["emails"] = [f"LOAD f TO VERTEX EmailDomain VALUES ($0) {OPTS};"]
    J["regions"] = [f"LOAD f TO VERTEX BillingRegion VALUES ($0) {OPTS};"]
    J["txns"] = [
        f"LOAD f TO VERTEX Transaction VALUES ({_vals(N + 1)}) {OPTS};",
        f"LOAD f TO EDGE MADE VALUES (${IDX['card_id']}, $0) {OPTS};",
        f"LOAD f TO EDGE FROM_DEVICE VALUES ($0, ${IDX_DEVICE_KEY}) WHERE ${IDX_DEVICE_KEY} != \"\" {OPTS};",
        f"LOAD f TO EDGE PURCHASER_EMAIL VALUES ($0, ${IDX['p_email']}) WHERE ${IDX['p_email']} != \"\" {OPTS};",
        f"LOAD f TO EDGE RECIPIENT_EMAIL VALUES ($0, ${IDX['r_email']}) WHERE ${IDX['r_email']} != \"\" {OPTS};",
        f"LOAD f TO EDGE BILLED_IN VALUES ($0, ${IDX_REGION}) WHERE ${IDX_REGION} != \"\" {OPTS};",
    ]
    J["next"] = [f"LOAD f TO EDGE NEXT VALUES ($0, $1, $2) {OPTS};"]
    J["closed_cases"] = [f"LOAD f TO VERTEX ClosedCase VALUES ({_vals(13)}) {OPTS};",
                         f"LOAD f TO EDGE CC_ON_CARD VALUES ($0, $2) {OPTS};"]
    J["involves"] = [f"LOAD f TO EDGE INVOLVES VALUES ($0, $1) {OPTS};"]
    J["cc_connected"] = [f"LOAD f TO EDGE CC_CONNECTED_TO VALUES ($0, $1) {OPTS};"]
    return J


def ddl_one(graph, name, loads):
    body = "\n  ".join(loads)
    return f"CREATE LOADING JOB load_{name} FOR GRAPH {graph} {{\n  DEFINE FILENAME f;\n  {body}\n}}\n"
