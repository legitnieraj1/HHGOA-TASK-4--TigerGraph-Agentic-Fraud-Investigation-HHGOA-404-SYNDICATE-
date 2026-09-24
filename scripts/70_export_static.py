"""Export the read-only API as static JSON for the Vercel deployment.

The deployed site serves browsing (case list, case detail, evidence subgraph) as static files and proxies
only the live endpoints (investigate, approve) to the agent backend. That split is deliberate: browsing is
what a judge does 95% of the time, and serving it statically means it renders instantly and cannot fail on
a cold Savanna workspace.

The payloads are produced by calling api.main's own endpoint functions rather than re-deriving them here,
so the static output cannot drift from what the live API returns.

Run: .venv/bin/python scripts/70_export_static.py   (then `npm run build` in ui/)
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.main import list_cases, get_case, case_subgraph  # noqa: E402

OUT = ROOT / "ui" / "public" / "static-api"


def write(rel: str, payload) -> int:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, default=str)
    path.write_text(body)
    return len(body)


def main():
    if OUT.exists():
        for stale in OUT.rglob("*.json"):
            stale.unlink()

    # LIVE-* are local test runs from the investigate panel (gitignored, not part of the submission set).
    # Cases created live against the deployed backend are fetched from it directly, not from here.
    cases = [c for c in list_cases() if not c["case_id"].startswith("LIVE-")]
    total = write("health.json", {"ok": True, "mode": "static", "cases_on_disk": len(cases)})
    total += write("cases.json", cases)

    for row in cases:
        cid = row["case_id"]
        total += write(f"cases/{cid}.json", get_case(cid))
        total += write(f"cases/{cid}.subgraph.json", case_subgraph(cid))

    print(f"exported {len(cases)} cases -> {OUT.relative_to(ROOT)} ({total / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
