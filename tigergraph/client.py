"""Thin TigerGraph Savanna client: secret -> token (cached, auto-refresh), GSQL over REST, REST++ helpers.

Never logs the secret or token. Config comes from .env (TG_HOST, TG_SECRET, TG_GRAPH)."""
import json
import os
import pathlib
import time

import requests
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TOKEN_CACHE = ROOT / ".tg_token"
TOKEN_LIFETIME_S = 3600 * 6


class TGError(RuntimeError):
    pass


class TG:
    def __init__(self, host=None, secret=None, graph=None, timeout=120):
        self.host = host or os.environ["TG_HOST"]
        self.secret = secret or os.environ["TG_SECRET"]
        self.graph = graph or os.environ.get("TG_GRAPH", "FraudGraph")
        self.timeout = timeout
        self.base = f"https://{self.host}"
        self._token = None
        self._exp = 0.0
        self.calls = 0  # tool-call counter surfaced in answer files

    # ---- auth ----
    def wake(self, max_wait=90):
        """Savanna auto-suspends the workspace on idle (configured 20 min) and auto-resumes on traffic, but the first
        ~20s of resume serves a 'Starting workspace' HTML page (502) instead of the API. Poll /restpp/echo until it's up."""
        t0 = time.time()
        while time.time() - t0 < max_wait:
            try:
                r = requests.get(f"{self.base}/restpp/echo", timeout=15)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    return True
            except requests.RequestException:
                pass
            time.sleep(3)
        return False

    def token(self, force=False):
        now = time.time()
        if not force and self._token and now < self._exp - 60:
            return self._token
        if not force and TOKEN_CACHE.exists():
            try:
                c = json.loads(TOKEN_CACHE.read_text())
                if c["host"] == self.host and now < c["exp"] - 60:
                    self._token, self._exp = c["token"], c["exp"]
                    return self._token
            except Exception:
                pass
        self.wake()
        r = requests.post(f"{self.base}/gsql/v1/tokens", timeout=self.timeout,
                          json={"secret": self.secret, "lifetime": str(TOKEN_LIFETIME_S)})
        try:
            d = r.json()
        except ValueError:
            raise TGError(f"token request non-JSON ({r.status_code}), workspace may still be waking: {r.text[:200]}")
        if r.status_code != 200 or d.get("error"):
            raise TGError(f"token request failed: {r.status_code} {d.get('message')}")
        self._token, self._exp = d["token"], now + TOKEN_LIFETIME_S
        TOKEN_CACHE.write_text(json.dumps({"host": self.host, "token": self._token, "exp": self._exp}))
        os.chmod(TOKEN_CACHE, 0o600)
        return self._token

    def _h(self, extra=None):
        h = {"Authorization": f"Bearer {self.token()}"}
        h.update(extra or {})
        return h

    def _req(self, method, path, retry=True, **kw):
        self.calls += 1
        kw.setdefault("timeout", self.timeout)
        r = requests.request(method, f"{self.base}{path}", **kw)
        if r.status_code == 401 and retry:  # expired token
            self.token(force=True)
            kw["headers"] = self._h({k: v for k, v in kw.get("headers", {}).items() if k != "Authorization"})
            return self._req(method, path, retry=False, **kw)
        if r.status_code in (502, 503) and retry:  # workspace mid-wake or transient gateway hiccup
            self.wake()
            return self._req(method, path, retry=False, **kw)
        return r

    # ---- GSQL ----
    def gsql(self, text, graph=None, check=True, retry=True):
        """Run GSQL text via /gsql/v1/statements. Returns raw text output. Same Savanna wake-page gotcha
        as rest(): a mid-wake HTML body doesn't match any of _looks_failed()'s failure strings, so without
        this check a wake race would silently look like a successful (empty/garbage) GSQL result instead
        of erroring -- worse than rest()'s crash, since it could pass silently."""
        params = {"graph": graph} if graph else None
        r = self._req("POST", "/gsql/v1/statements", params=params, data=text.encode(),
                      headers=self._h({"Content-Type": "text/plain"}))
        out = r.text
        if retry and "Starting workspace" in out:
            self.wake()
            return self.gsql(text, graph=graph, check=check, retry=False)
        if check and (r.status_code >= 400 or _looks_failed(out)):
            raise TGError(f"GSQL failed ({r.status_code}):\n{out[:2000]}")
        return out

    # ---- REST++ ----
    def rest(self, method, path, retry=True, **kw):
        """Savanna's wake page is a real gotcha: mid-wake it can return HTTP 200 (not 502/503) with an
        HTML 'Starting workspace' body instead of JSON -- _req()'s status-code retry never sees it since
        the status itself looks fine. Caught live via the UI's investigate panel after 20 min idle
        auto-suspended the workspace (NOTES.md's own auto-suspend config working as intended). Detect the
        non-JSON body here and retry once through wake(), same recovery path as the 502/503 case."""
        kw["headers"] = self._h(kw.pop("headers", None))
        r = self._req(method, path, **kw)
        try:
            return r.json()
        except Exception:
            if retry and "Starting workspace" in r.text:
                self.wake()
                return self.rest(method, path, retry=False, **kw)
            raise TGError(f"non-JSON REST response {r.status_code}: {r.text[:500]}")

    def upsert(self, payload):
        return self.rest("POST", f"/restpp/graph/{self.graph}", json=payload)

    def load_file(self, job, filename, data: bytes, sep=None, eol="\n"):
        """Stream a chunk to a loading job file placeholder (POST /restpp/ddl/<graph>)."""
        params = {"tag": job, "filename": filename, "sep": sep or ",", "eol": eol}
        return self.rest("POST", f"/restpp/ddl/{self.graph}", params=params, data=data,
                         headers={"Content-Type": "text/plain"}, timeout=600)

    def run_query(self, name, _retries=6, **params):
        """Call an installed query. A LIST-valued param (e.g. a 384-float embedding for vectorSearch) is sent as a
        JSON POST body -- a GET query string of that size is unwieldy and TigerGraph's list-as-repeated-key GET
        form is easy to get wrong. Scalar-only calls still use GET with percent-encoded values (%20, not '+':
        vertex ids like device keys contain spaces, '/' and '|').

        A THIRD Savanna cold-start state, distinct from the two rest()/gsql() already handle: the engine can be
        far enough awake to return a normal JSON error response ({"error": true, "message": "...failed to
        retrieve id map..."}) while its vertex id index is still rebuilding after a resume. Unlike the
        'Starting workspace' HTML page, this looks like a legitimate query failure to rest() -- only run_query's
        callers know it's transient. Retry with backoff (this can take 10-30s+ after a genuinely cold wake)."""
        # TigerGraph enforces its OWN query timeout server-side, default 60s, entirely separate from the
        # HTTP timeout below: raising only the client one lets requests fail at 60s while the client
        # happily waits 300. A genuinely cold Savanna workspace routinely needs more than 60s for the
        # first query, which failed a live run with "exceeded the query timeout threshold (60 seconds)".
        # GSQL-TIMEOUT overrides it per request and is in MILLISECONDS.
        hdr = {"GSQL-TIMEOUT": "280000"}
        if any(isinstance(v, (list, tuple)) for v in params.values()):
            call = lambda: self.rest("POST", f"/restpp/query/{self.graph}/{name}", json=params, headers=hdr, timeout=300)  # noqa: E731
        else:
            from urllib.parse import quote
            qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
            call = lambda: self.rest("GET", f"/restpp/query/{self.graph}/{name}" + (f"?{qs}" if qs else ""), headers=hdr, timeout=300)  # noqa: E731

        import time as _time
        for attempt in range(_retries):
            result = call()
            msg = ((result.get("message") or "") if isinstance(result, dict) else "").lower()
            # Both are cold-start symptoms, not real query failures: the vertex id index still rebuilding,
            # and the engine too cold to finish inside its own deadline. A timeout has already burned its
            # full budget, so it gets far fewer attempts than the cheap id-map case.
            transient = "id map" in msg or "query timeout threshold" in msg
            budget = 2 if "query timeout threshold" in msg else _retries
            if result.get("error") and transient and attempt < min(budget, _retries) - 1:
                _time.sleep(min(3 * (attempt + 1), 15))
                continue
            return result
        return result

    def stats(self):
        return self.rest("POST", f"/restpp/builtins/{self.graph}", json={"function": "stat_vertex_number", "type": "*"})

    def edge_stats(self):
        return self.rest("POST", f"/restpp/builtins/{self.graph}", json={"function": "stat_edge_number", "type": "*"})


def _looks_failed(out: str) -> bool:
    low = out.lower()
    return any(s in low for s in ("semantic error", "syntax error", "failed to", "error:", "is not a valid", "does not exist",
                                  "already exists", "could not", "encountered", "reserved keyword",
                                  "semantic check fails", "was expecting"))
