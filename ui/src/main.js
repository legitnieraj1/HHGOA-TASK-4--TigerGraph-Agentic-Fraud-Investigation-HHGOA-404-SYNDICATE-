import "./theme.scss";
import "./app.css";

// Real @carbon/web-components custom elements (cds- prefix, verified against the installed package's
// own carbonElement() registrations, not guessed). Importing only what the page uses.
import "@carbon/web-components/es/components/ui-shell/header.js";
import "@carbon/web-components/es/components/ui-shell/header-name.js";
import "@carbon/web-components/es/components/button/index.js";
import "@carbon/web-components/es/components/tag/tag.js";
import "@carbon/web-components/es/components/tile/tile.js";
import "@carbon/web-components/es/components/notification/inline-notification.js";
import "@carbon/web-components/es/components/text-input/text-input.js";
import "@carbon/web-components/es/components/form-group/form-group.js";
import "@carbon/web-components/es/components/loading/loading.js";

import { renderSubgraph, SUBGRAPH_LEGEND, legendColour } from "./subgraph.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// Where the live agent lives. Empty locally (same origin serves both the UI and the full FastAPI app);
// set to the backend's URL at build time for the Vercel deployment, where browsing is served as static
// JSON and only the live endpoints reach a real server. Build with:
//   VITE_AGENT_API=https://<backend-host> npm run build
const AGENT_API = (import.meta.env.VITE_AGENT_API || "").replace(/\/$/, "");

/**
 * GET a read endpoint. On the deployment these are static files, so a case created live against the
 * backend is not in that set: fall back to the backend before giving up, otherwise a judge who triggers
 * an investigation gets a 404 on the case they just created.
 */
async function apiGet(path) {
  const r = await fetch(path);
  if (r.ok) return r.json();
  if (AGENT_API) {
    const live = await fetch(`${AGENT_API}${path}`);
    if (live.ok) return live.json();
  }
  throw new Error(`GET ${path} failed (${r.status})`);
}

const apiPost = (path, body) =>
  fetch(`${AGENT_API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// verdict -> Carbon tag `type` (real Carbon tag color tokens: red/green/purple/gray/blue etc, not invented hex)
const VERDICT_TAG = { fraud: "red", legitimate: "green", uncertain: "purple", escalated: "purple" };
const ROUTE_TAG = { auto: "green", L1: "purple", L2: "red" };

let currentCase = null;
let destroySubgraph = () => {};   // stops the previous case's force simulation before the next renders

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

const money = (n) => "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });

/**
 * The portfolio view, shown until a case is opened. Every figure is computed from the real case files,
 * nothing here is illustrative. This is the first thing a visitor sees, so it carries the headline
 * result rather than an instruction to go click something.
 */
function renderOverview(cases) {
  const fraud = cases.filter((c) => c.verdict === "fraud").length;
  const legit = cases.filter((c) => c.verdict === "legitimate").length;
  const exposure = cases.reduce((s, c) => s + c.exposure_usd, 0);
  const sars = cases.filter((c) => c.sar_filed).length;
  const pending = cases.reduce((s, c) => s + c.pending_approvals, 0);

  const stat = (value, label) =>
    `<div class="stat"><div class="stat-value">${value}</div><div class="stat-label cds-label-01">${label}</div></div>`;

  $("#case-detail").innerHTML = `
    <div class="overview">
      <h1 class="overview-title">Agentic fraud investigation</h1>
      <p class="overview-lede cds-body-compact-02">
        Every case below was investigated against a live TigerGraph graph. Evidence comes from installed
        GSQL queries; actions stay gated behind the approval policy.
      </p>
      <div class="stat-row">
        ${stat(cases.length, "cases closed")}
        ${stat(fraud, "fraud")}
        ${stat(legit, "legitimate")}
        ${stat(money(exposure), "exposure found")}
        ${stat(sars, "SARs filed")}
        ${stat(pending, "awaiting approval")}
      </div>
      <p class="overview-hint cds-label-01">Open a case to see the evidence subgraph behind its verdict.</p>
    </div>`;
}

async function loadCases() {
  const cases = await apiGet("/api/cases");
  if (!currentCase) renderOverview(cases);
  const list = $("#case-list");
  if (!cases.length) {
    list.innerHTML = `<div class="empty-state">No cases yet.<br/>Run <code>scripts/60_run_benchmark.py</code> or trigger one from the panel on the right.</div>`;
    return;
  }
  list.innerHTML = cases
    .map(
      (c) => `
    <div class="case-row" data-id="${esc(c.case_id)}">
      <div class="id-row">
        <span class="cds-heading-compact-01">${esc(c.case_id)}</span>
        ${c.pending_approvals ? `<cds-tag type="purple" size="sm">${c.pending_approvals} pending</cds-tag>` : ""}
      </div>
      <div class="tags">
        <cds-tag type="${VERDICT_TAG[c.verdict] || "gray"}" size="sm">${esc(c.verdict)}</cds-tag>
        <span class="cds-label-01" style="color:var(--cds-text-secondary)">${esc(c.pattern)}</span>
      </div>
      <div class="meta cds-label-01">$${c.exposure_usd.toLocaleString()} &middot; p=${c.fraud_probability.toFixed(2)}${c.sar_filed ? " &middot; SAR" : ""}</div>
    </div>`
    )
    .join("");
  $$(".case-row", list).forEach((el) => (el.onclick = () => openCase(el.dataset.id)));
}

function meterColor(p) {
  if (p >= 0.6) return "var(--cds-support-error)";
  if (p >= 0.35) return "var(--cds-support-warning)";
  return "var(--cds-support-success)";
}

function nbaRow(a, phase, approvals) {
  const decided = approvals[a.action];
  let control;
  if (a.route === "auto") {
    control = `<span class="cds-label-01" style="color:var(--cds-text-secondary)">Auto-executed</span>`;
  } else if (decided) {
    control = `<cds-tag type="${decided === "approved" ? "green" : "red"}" size="sm">${decided}</cds-tag>`;
  } else if (phase === "final") {
    control = `<div class="buttons">
      <cds-button kind="primary" size="sm" data-approve="${esc(a.action)}">Approve</cds-button>
      <cds-button kind="danger--tertiary" size="sm" data-reject="${esc(a.action)}">Reject</cds-button>
    </div>`;
  } else {
    control = `<span class="cds-label-01" style="color:var(--cds-text-placeholder)">Pending</span>`;
  }
  return `<div class="action-row">
    <div class="name cds-body-compact-02">${esc(a.action)} <cds-tag type="${ROUTE_TAG[a.route] || "gray"}" size="sm">${esc(a.route)}</cds-tag></div>
    <div class="reason cds-label-01">${esc(a.reason)}</div>
    ${control}
  </div>`;
}

async function openCase(id) {
  currentCase = id;
  destroySubgraph();
  $$(".case-row").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const d = await apiGet(`/api/cases/${id}`);
  const c = d.case;
  const approvals = d._approvals || {};

  const evRows = c.evidence
    .map((e) => `<div class="evidence-item"><div class="src cds-label-01">${esc(e.source)} &middot; ${esc(e.ref)}</div><div class="cds-body-compact-01">${esc(e.claim)}</div></div>`)
    .join("");

  const legend = SUBGRAPH_LEGEND.map(
    ([key, label]) =>
      `<span class="sg-key cds-label-01"><i style="background:${legendColour(key)}"></i>${label}</span>`
  ).join("");

  $("#case-detail").innerHTML = `
    <header class="case-head">
      <div class="case-head-top">
        <h1 class="case-id">${esc(id)}</h1>
        <cds-tag type="${VERDICT_TAG[c.verdict] || "gray"}">${esc(c.verdict)}</cds-tag>
        ${d.sar.file ? `<cds-tag type="red">SAR filed</cds-tag>` : ""}
      </div>
      <div class="case-meta">
        <span>${esc(c.pattern)}</span>
        <span>p=${c.fraud_probability.toFixed(2)}</span>
        <span>${c.exposure_usd ? money(c.exposure_usd) + " exposure" : "no exposure"}</span>
      </div>
    </header>

    <section class="section">
      <h2 class="cds-label-01">Evidence subgraph</h2>
      <div class="sg-wrap" id="subgraph"></div>
      <div class="sg-legend">${legend}</div>
      <div class="sg-note cds-label-01">Drag a node to pull the structure apart. Hover for the query that produced it.</div>
    </section>

    <section class="section">
      <h2 class="cds-label-01">Timeline</h2>
      <div class="timeline-row">
        <span class="timeline-chip cds-label-01">trigger</span>
        <span class="timeline-chip cds-label-01">evidence (${c.evidence.length})</span>
        <span class="timeline-chip cds-label-01">assess</span>
        <span class="timeline-chip cds-label-01">${d.evidence_requests.length} evidence request(s)</span>
        <span class="timeline-chip cds-label-01">${d.next_best_actions.final.length} action(s)</span>
        <span class="timeline-chip cds-label-01">${esc(c.status)}</span>
      </div>
      <div class="lede cds-body-compact-01">${esc(c.summary)}</div>
    </section>

    <section class="section">
      <h2 class="cds-label-01">Uncertainty &middot; fraud probability ${c.fraud_probability.toFixed(2)} (${esc(c.verdict)})</h2>
      <div class="meter-track"><div class="meter-fill" style="width:${c.fraud_probability * 100}%;background:${meterColor(c.fraud_probability)}"></div></div>
      <div class="cds-body-compact-01" style="color:var(--cds-text-secondary)">${esc(d.stop_reason)}</div>
    </section>

    <section class="section">
      <h2 class="cds-label-01">Evidence &middot; ${esc(c.pattern)}${c.pattern_description ? ": " + esc(c.pattern_description) : ""}</h2>
      ${evRows}
    </section>

    <section class="section">
      <h2 class="cds-label-01">Next best action &middot; before / after evidence</h2>
      <div class="nba-grid">
        <div class="nba-col"><h3>Initial</h3>${d.next_best_actions.initial.map((a) => nbaRow(a, "initial", approvals)).join("") || '<div class="cds-body-compact-01">None</div>'}</div>
        <div class="nba-col"><h3>Final</h3>${d.next_best_actions.final.map((a) => nbaRow(a, "final", approvals)).join("") || '<div class="cds-body-compact-01">None</div>'}</div>
      </div>
      <div class="what-changed">What changed: ${esc(d.next_best_actions.what_changed)}</div>
    </section>

    ${
      d.sar.file
        ? `<section class="section">
      <h2 class="cds-label-01">Suspicious Activity Report</h2>
      <div class="cds-body-compact-01" style="color:var(--cds-text-secondary)">${esc(d.sar.reason)}</div>
      <div class="sar-narrative cds-body-compact-01">${esc(d.sar.narrative)}</div>
      <div class="cds-label-01" style="color:var(--cds-text-secondary)">Subjects: ${esc(d.sar.subjects.join(", "))} &middot; $${d.sar.total_amount_usd.toLocaleString()} &middot; ${esc(d.sar.activity_dates.join(" to "))}</div>
    </section>`
        : ""
    }

    <section class="section">
      <h2 class="cds-label-01">Case memory</h2>
      <div class="cds-body-compact-01" style="color:var(--cds-text-secondary)">Similar prior cases: ${esc(c.similar_prior_cases.join(", ")) || "none"}</div>
      <div class="cds-body-compact-01" style="color:var(--cds-text-secondary)">Written to graph: ${c.written_to_graph ? `yes (${esc(c.graph_case_id)})` : "no"}</div>
    </section>
  `;

  $$("[data-approve]", $("#case-detail")).forEach((btn) => (btn.onclick = () => approve(btn.dataset.approve, "approved")));
  $$("[data-reject]", $("#case-detail")).forEach((btn) => (btn.onclick = () => approve(btn.dataset.reject, "rejected")));

  // Subgraph is fetched after the detail markup is in the DOM (it needs a sized container to lay out
  // into). Guarded on `currentCase` so a fast click-through doesn't render a stale case's graph.
  try {
    const g = await apiGet(`/api/cases/${id}/subgraph`);
    if (currentCase !== id) return;
    const host = $("#subgraph");
    if (host) destroySubgraph = renderSubgraph(host, g);
  } catch {
    const host = $("#subgraph");
    if (host) host.innerHTML = `<div class="sg-empty cds-label-01">Subgraph unavailable.</div>`;
  }
}

async function approve(action, decision) {
  const r = await apiPost(`/api/cases/${currentCase}/approve`, { action, decision });
  if (!r.ok) {
    window.alert(
      AGENT_API
        ? `Could not record the decision (HTTP ${r.status}). The agent backend may be waking up; try again.`
        : "Approvals need the agent backend. Run the stack locally to record a decision."
    );
    return;
  }
  openCase(currentCase);
}

function initChat() {
  // Carbon's cds-text-input / cds-button are NOT form-associated custom elements (verified against
  // the installed package: no ElementInternals/formAssociated anywhere in either source file) -- a
  // native <form> submit event never fires from clicking cds-button, and FormData(form) can't see
  // values living in cds-text-input's shadow DOM anyway. Reading each input's real `.value` property
  // directly and handling a plain click, not relying on native form submission at all.
  const submit = $("#chat-submit");
  const inputs = { txn: $("#txn"), card: $("#card"), cust: $("#cust"), reason: $("#reason") };

  submit.addEventListener("click", async () => {
    const vals = { txn: inputs.txn.value, card: inputs.card.value, cust: inputs.cust.value, reason: inputs.reason.value };
    if (!vals.txn || !vals.card || !vals.cust || !vals.reason) {
      Object.entries(inputs).forEach(([k, el]) => (el.invalid = !vals[k]));
      return;
    }
    Object.values(inputs).forEach((el) => (el.invalid = false));

    const log = $("#chat-log");
    const userMsg = `Investigate txn ${esc(vals.txn)} on ${esc(vals.card)}: ${esc(vals.reason)}`;
    log.insertAdjacentHTML("beforeend", `<div class="chat-msg user cds-body-compact-01">${userMsg}</div>`);
    const spinnerId = "sp-" + Date.now();
    log.insertAdjacentHTML("beforeend", `<div class="chat-msg cds-body-compact-01" id="${spinnerId}"><span class="spinner"></span> Investigating...</div>`);
    log.scrollTop = log.scrollHeight;
    try {
      const r = await apiPost("/api/investigate", {
        flagged_txn_id: parseInt(vals.txn, 10),
        card_id: vals.card,
        customer_id: vals.cust,
        trigger_text: vals.reason,
        trigger_type: "analyst_request",
      });
      // A backend 500 can come back as plain text ("Internal Server Error"), not JSON -- Starlette's
      // default error middleware does this for an unhandled exception. r.json() would throw and land
      // in the outer catch as an opaque "SyntaxError: Unexpected token" instead of the real message.
      const raw = await r.text();
      let d = null;
      try { d = JSON.parse(raw); } catch { /* not JSON, fall through */ }
      $(`#${spinnerId}`).outerHTML = r.ok && d
        ? `<div class="chat-msg cds-body-compact-01">Done. <strong>${esc(d.case_id)}</strong>: ${esc(d.case.verdict)} / ${esc(d.case.pattern)} (p=${d.case.fraud_probability.toFixed(2)}). ${esc(d.case.summary)}</div>`
        : `<div class="chat-msg cds-body-compact-01">Error (HTTP ${r.status}): ${esc(d ? JSON.stringify(d) : raw.slice(0, 300))}</div>`;
      await loadCases();
      if (r.ok) openCase(d.case_id);
    } catch (err) {
      $(`#${spinnerId}`).outerHTML = `<div class="chat-msg cds-body-compact-01">Error: ${esc(String(err))}</div>`;
    }
    Object.values(inputs).forEach((el) => (el.value = ""));
  });
}

document.querySelector("#app").innerHTML = `
  <cds-header aria-label="Fraud Investigation Agent">
    <cds-header-name href="/" prefix="TigerGraph">Fraud Investigation Agent</cds-header-name>
  </cds-header>
  <div class="layout">
    <div class="col list" id="case-list"></div>
    <div class="col detail" id="case-detail"></div>
    <div class="col chat">
      <div class="chat-log" id="chat-log">
        <div class="chat-msg cds-body-compact-01">Trigger or steer a live investigation. Give a flagged transaction id, card id and customer id from the dataset, and a reason.</div>
      </div>
      <div class="chat-form" id="chat-form">
        <div class="field-group"><label class="cds-label-01" for="txn">Flagged transaction id</label><cds-text-input id="txn" placeholder="e.g. 3514030" invalid-text="Required"></cds-text-input></div>
        <div class="field-group"><label class="cds-label-01" for="card">Card id</label><cds-text-input id="card" placeholder="e.g. C12382-K1" invalid-text="Required"></cds-text-input></div>
        <div class="field-group"><label class="cds-label-01" for="cust">Customer id</label><cds-text-input id="cust" placeholder="e.g. C12382" invalid-text="Required"></cds-text-input></div>
        <div class="field-group"><label class="cds-label-01" for="reason">Reason</label><cds-text-input id="reason" placeholder="e.g. analyst spotted unusual activity" invalid-text="Required"></cds-text-input></div>
        <cds-button id="chat-submit" kind="primary">Investigate</cds-button>
      </div>
    </div>
  </div>
`;

initChat();
loadCases();
