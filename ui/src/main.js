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

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// verdict -> Carbon tag `type` (real Carbon tag color tokens: red/green/purple/gray/blue etc, not invented hex)
const VERDICT_TAG = { fraud: "red", legitimate: "green", uncertain: "purple", escalated: "purple" };
const ROUTE_TAG = { auto: "green", L1: "purple", L2: "red" };

let currentCase = null;

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function loadCases() {
  const health = await (await fetch("/api/health")).json();
  const cases = await (await fetch("/api/cases")).json();
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
  $$(".case-row").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const d = await (await fetch(`/api/cases/${id}`)).json();
  const c = d.case;
  const approvals = d._approvals || {};

  const evRows = c.evidence
    .map((e) => `<div class="evidence-item"><div class="src cds-label-01">${esc(e.source)} &middot; ${esc(e.ref)}</div><div class="cds-body-compact-01">${esc(e.claim)}</div></div>`)
    .join("");

  $("#case-detail").innerHTML = `
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
}

async function approve(action, decision) {
  await fetch(`/api/cases/${currentCase}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, decision }),
  });
  openCase(currentCase);
}

function initChat() {
  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const log = $("#chat-log");
    const userMsg = `Investigate txn ${esc(fd.get("flagged_txn_id"))} on ${esc(fd.get("card_id"))}: ${esc(fd.get("trigger_text"))}`;
    log.insertAdjacentHTML("beforeend", `<div class="chat-msg user cds-body-compact-01">${userMsg}</div>`);
    const spinnerId = "sp-" + Date.now();
    log.insertAdjacentHTML("beforeend", `<div class="chat-msg cds-body-compact-01" id="${spinnerId}"><span class="spinner"></span> Investigating...</div>`);
    log.scrollTop = log.scrollHeight;
    try {
      const r = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          flagged_txn_id: parseInt(fd.get("flagged_txn_id"), 10),
          card_id: fd.get("card_id"),
          customer_id: fd.get("customer_id"),
          trigger_text: fd.get("trigger_text"),
          trigger_type: "analyst_request",
        }),
      });
      const d = await r.json();
      $(`#${spinnerId}`).outerHTML = r.ok
        ? `<div class="chat-msg cds-body-compact-01">Done. <strong>${esc(d.case_id)}</strong>: ${esc(d.case.verdict)} / ${esc(d.case.pattern)} (p=${d.case.fraud_probability.toFixed(2)}). ${esc(d.case.summary)}</div>`
        : `<div class="chat-msg cds-body-compact-01">Error: ${esc(JSON.stringify(d))}</div>`;
      await loadCases();
      if (r.ok) openCase(d.case_id);
    } catch (err) {
      $(`#${spinnerId}`).outerHTML = `<div class="chat-msg cds-body-compact-01">Error: ${esc(String(err))}</div>`;
    }
    e.target.reset();
  });
}

document.querySelector("#app").innerHTML = `
  <cds-header aria-label="Fraud Investigation Agent">
    <cds-header-name href="/" prefix="TigerGraph">Fraud Investigation Agent</cds-header-name>
  </cds-header>
  <div class="layout">
    <div class="col list" id="case-list"></div>
    <div class="col detail" id="case-detail"><div class="empty-state">Select a case on the left.</div></div>
    <div class="col chat">
      <div class="chat-log" id="chat-log">
        <div class="chat-msg cds-body-compact-01">Trigger or steer a live investigation. Give a flagged transaction id, card id and customer id from the dataset, and a reason.</div>
      </div>
      <form class="chat-form" id="chat-form">
        <cds-form-group class="field-group" legend-text="">
          <div class="field-group"><label class="cds-label-01" for="txn">Flagged transaction id</label><cds-text-input id="txn" name="flagged_txn_id" placeholder="e.g. 3514030" required></cds-text-input></div>
        </cds-form-group>
        <div class="field-group"><label class="cds-label-01" for="card">Card id</label><cds-text-input id="card" name="card_id" placeholder="e.g. C12382-K1" required></cds-text-input></div>
        <div class="field-group"><label class="cds-label-01" for="cust">Customer id</label><cds-text-input id="cust" name="customer_id" placeholder="e.g. C12382" required></cds-text-input></div>
        <div class="field-group"><label class="cds-label-01" for="reason">Reason</label><cds-text-input id="reason" name="trigger_text" placeholder="e.g. analyst spotted unusual activity" required></cds-text-input></div>
        <cds-button kind="primary" type="submit">Investigate</cds-button>
      </form>
    </div>
  </div>
`;

initChat();
loadCases();
