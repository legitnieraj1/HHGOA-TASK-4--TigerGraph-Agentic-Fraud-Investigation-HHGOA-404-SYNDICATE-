"""FastAPI backend for the analyst dashboard (spec Phase 7): case list, per-case detail (timeline, evidence,
uncertainty, before/after NBA, SAR), approval actions, and a conversational endpoint to trigger/steer live
investigations. Serves the static dashboard from ui/. Run: .venv/bin/uvicorn api.main:app --reload --port 8080"""
import json
import pathlib
import sys
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES_DIR = ROOT / "cases"
CASES_DIR.mkdir(exist_ok=True)
APPROVALS_FILE = ROOT / "data" / "approvals.json"  # {case_id: {action: "approved"|"rejected"}}

app = FastAPI(title="Fraud Investigation Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_tg = None  # lazy singleton -- TigerGraph connects on first use, not at import time


def get_tg():
    global _tg
    if _tg is None:
        from tigergraph.client import TG
        _tg = TG()
    return _tg


def load_approvals() -> dict:
    if APPROVALS_FILE.exists():
        return json.loads(APPROVALS_FILE.read_text())
    return {}


def save_approvals(d: dict):
    APPROVALS_FILE.write_text(json.dumps(d, indent=2))


@app.get("/api/health")
def health():
    return {"ok": True, "cases_on_disk": len(list(CASES_DIR.glob("*.json")))}


@app.get("/api/cases")
def list_cases():
    approvals = load_approvals()
    out = []
    for f in sorted(CASES_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        c = d["case"]
        pending = [a for a in d["next_best_actions"]["final"] if a["route"] != "auto"
                  and approvals.get(d["case_id"], {}).get(a["action"]) != "approved"]
        out.append({"case_id": d["case_id"], "status": c["status"], "verdict": c["verdict"],
                   "pattern": c["pattern"], "fraud_probability": c["fraud_probability"],
                   "exposure_usd": c["exposure_usd"], "sar_filed": d["sar"]["file"],
                   "pending_approvals": len(pending)})
    return out


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    f = CASES_DIR / f"{case_id}.json"
    if not f.exists():
        f2 = ROOT / "outputs" / "cases_dev" / f"{case_id}.json"
        if not f2.exists():
            raise HTTPException(404, f"no case file for {case_id}")
        f = f2
    d = json.loads(f.read_text())
    d["_approvals"] = load_approvals().get(case_id, {})
    return d


class ApprovalRequest(BaseModel):
    action: str
    decision: str  # "approved" | "rejected"


@app.post("/api/cases/{case_id}/approve")
def approve(case_id: str, req: ApprovalRequest):
    f = CASES_DIR / f"{case_id}.json"
    if not f.exists():
        raise HTTPException(404, f"no case file for {case_id}")
    d = json.loads(f.read_text())
    valid_actions = {a["action"] for a in d["next_best_actions"]["final"]}
    if req.action not in valid_actions:
        raise HTTPException(400, f"{req.action} is not a recommended action on {case_id}")
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")
    approvals = load_approvals()
    approvals.setdefault(case_id, {})[req.action] = req.decision
    save_approvals(approvals)
    # Log the human decision to the graph as an Action status update (auditable, matches the spec's
    # "a judge clicks approve" requirement being a real, recorded event, not just UI state).
    tg = get_tg()
    action_id = f"{case_id}-A{valid_actions_index(d, req.action)}"
    tg.upsert({"vertices": {"Action": {action_id: {"status": {"value": f"human_{req.decision}"}}}}})
    return {"case_id": case_id, "action": req.action, "decision": req.decision, "logged_to_graph": True}


def valid_actions_index(d: dict, action: str) -> int:
    for i, a in enumerate(d["next_best_actions"]["final"]):
        if a["action"] == action:
            return i + 1
    return 0


class InvestigateRequest(BaseModel):
    case_id: str | None = None      # an existing case_pack/closed-case id to re-run
    trigger_type: str = "analyst_request"
    trigger_text: str
    flagged_txn_id: int
    card_id: str
    customer_id: str


@app.post("/api/investigate")
def investigate(req: InvestigateRequest):
    """The conversational panel's live-trigger endpoint. Runs synchronously (a case takes ~15-25s); the UI
    shows a spinner. Writes the result to cases/ like any other run, so it shows up in the case list."""
    from agent.graph import run_case
    from agent.answer import build
    case_id = req.case_id or f"LIVE-{int(time.time())}"
    tg = get_tg()
    state = run_case(tg, case_id=case_id, trigger_type=req.trigger_type, trigger_text=req.trigger_text,
                     opened_at=time.strftime("%Y-%m-%d %H:%M:%S"), flagged_txn_id=req.flagged_txn_id,
                     card_id=req.card_id, customer_id=req.customer_id)
    answer = build(state)
    (CASES_DIR / f"{case_id}.json").write_text(json.dumps(answer, indent=2, default=str))
    return answer


app.mount("/", StaticFiles(directory=str(ROOT / "ui" / "dist"), html=True), name="ui")
