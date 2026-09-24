// Evidence subgraph renderer (spec Phase 7: "an evidence subgraph visualisation").
//
// Force-directed layout via d3-force (verified installed: d3-force@3.0.0), drawn to a canvas.
// Canvas over SVG because the force tick rate is what makes the ring structure legible as it settles,
// and 15-odd nodes hit-test fine by hand without a DOM node each.
//
// Motion is motivated, not decorative: watching a device-ring case pull 6 cards onto one device is the
// single clearest way to show what the graph found. Under `prefers-reduced-motion` the simulation is run
// to completion synchronously and drawn once, so the same structure lands with zero animation.
//
// Every colour comes from the tokens already defined in theme.scss (read at runtime, so the theme stays
// the single source of truth). Node colour here encodes vertex type -- categorical data encoding, which
// is why this is more than one accent; it is not brand decoration.
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// vertex type -> [radius, colour token]. Falls back to a neutral if a new type ever appears.
const STYLE = {
  case: [9, "--brand-offwhite"],
  card: [7, "--cds-text-secondary"],
  card_subject: [9, "--brand-accent"],
  transaction: [5, "--cds-text-secondary"],
  transaction_flagged: [8, "--cds-support-error"],
  device: [8, "--brand-pink"],
  customer: [6, "--brand-offwhite"],
  prior_case: [5, "--brand-primary-light"],
};

const styleFor = (n) => {
  const key = n.subject ? "card_subject" : n.flagged ? "transaction_flagged" : n.type;
  return STYLE[key] || STYLE[n.type] || [5, "--cds-text-secondary"];
};

const shortLabel = (s) => (s.length > 15 ? s.slice(0, 14) + "…" : s);

/**
 * Render an evidence subgraph into `container`. Returns a destroy() that stops the simulation and
 * detaches every listener -- openCase() calls it before rendering the next case, otherwise old
 * simulations keep ticking against a detached canvas.
 */
export function renderSubgraph(container, data) {
  container.innerHTML = "";
  if (!data.nodes.length) {
    container.innerHTML = `<div class="sg-empty cds-label-01">No graph entities on this case.</div>`;
    return () => {};
  }

  const canvas = document.createElement("canvas");
  canvas.className = "sg-canvas";
  const tip = document.createElement("div");
  tip.className = "sg-tip cds-label-01";
  tip.hidden = true;
  container.append(canvas, tip);

  const ctx = canvas.getContext("2d");
  // d3-force mutates the objects it is given, so copy: the cached API response stays clean.
  const nodes = data.nodes.map((n) => ({ ...n }));
  const links = data.edges.map((e) => ({ ...e }));

  let w = 0;
  let h = 0;
  let hovered = null;
  let dragging = null;

  const resize = () => {
    const dpr = window.devicePixelRatio || 1;
    w = container.clientWidth;
    h = container.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    sim.force("center", forceCenter(w / 2, h / 2));
    sim.alpha(0.4).restart();
  };

  const sim = forceSimulation(nodes)
    .force("link", forceLink(links).id((d) => d.id).distance(62).strength(0.55))
    .force("charge", forceManyBody().strength(-230))
    .force("collide", forceCollide().radius((d) => styleFor(d)[0] + 9))
    .force("center", forceCenter(0, 0));

  function draw() {
    ctx.clearRect(0, 0, w, h);
    const dim = hovered ? 0.18 : 1;
    const near = (n) =>
      !hovered ||
      n.id === hovered.id ||
      links.some(
        (l) =>
          (l.source.id === hovered.id && l.target.id === n.id) ||
          (l.target.id === hovered.id && l.source.id === n.id)
      );

    ctx.lineWidth = 1;
    for (const l of links) {
      const lit = !hovered || l.source.id === hovered.id || l.target.id === hovered.id;
      ctx.globalAlpha = lit ? 0.55 : dim;
      ctx.strokeStyle = token("--cds-border-subtle-01") || "#525252";
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
      // Edge type only when hovering it: 18 labels at once is noise, 3 is information.
      if (hovered && lit) {
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = token("--cds-text-placeholder") || "#6f6f6f";
        ctx.font = `9px ${token("--font-brand-mono") || "monospace"}`;
        ctx.textAlign = "center";
        ctx.fillText(l.label, (l.source.x + l.target.x) / 2, (l.source.y + l.target.y) / 2 - 3);
      }
    }

    for (const n of nodes) {
      const [r, colourToken] = styleFor(n);
      const lit = near(n);
      ctx.globalAlpha = lit ? 1 : dim;
      ctx.fillStyle = token(colourToken) || "#a8a8a8";
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fill();
      if (n.subject || n.flagged) {
        // A ring on the two nodes the case is actually about, so the eye lands there first.
        ctx.globalAlpha = lit ? 0.45 : dim;
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.lineWidth = 1;
      }
      ctx.globalAlpha = lit ? 0.85 : dim;
      ctx.fillStyle = token("--cds-text-secondary") || "#c6c6c6";
      ctx.font = `10px ${token("--font-brand-mono") || "monospace"}`;
      ctx.textAlign = "center";
      ctx.fillText(shortLabel(n.label), n.x, n.y + r + 11);
    }
    ctx.globalAlpha = 1;
  }

  const at = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;
    let hit = null;
    for (const n of nodes) {
      const r = styleFor(n)[0] + 6;
      if ((n.x - x) ** 2 + (n.y - y) ** 2 < r * r) hit = n;
    }
    return { x, y, hit };
  };

  const onMove = (ev) => {
    const { x, y, hit } = at(ev);
    if (dragging) {
      dragging.fx = x;
      dragging.fy = y;
      return;
    }
    if (hit !== hovered) {
      hovered = hit;
      canvas.style.cursor = hit ? "grab" : "default";
      draw();
    }
    if (hit) {
      tip.hidden = false;
      tip.innerHTML = `<strong>${hit.type.replace("_", " ")}</strong> ${hit.label}<br/><span class="sg-via">${hit.via}</span>`;
      // Flip the tooltip before it runs off the right edge rather than letting it clip.
      const flip = x > w - 190;
      tip.style.left = `${flip ? x - 12 : x + 12}px`;
      tip.style.top = `${Math.min(y + 12, h - 54)}px`;
      tip.style.transform = flip ? "translateX(-100%)" : "none";
    } else {
      tip.hidden = true;
    }
  };

  const onDown = (ev) => {
    const { hit } = at(ev);
    if (!hit) return;
    dragging = hit;
    hit.fx = hit.x;
    hit.fy = hit.y;
    sim.alphaTarget(0.25).restart();
    canvas.style.cursor = "grabbing";
  };

  const onUp = () => {
    if (!dragging) return;
    dragging.fx = null;
    dragging.fy = null;
    dragging = null;
    sim.alphaTarget(0);
    canvas.style.cursor = "grab";
  };

  const onLeave = () => {
    onUp();
    if (hovered) {
      hovered = null;
      draw();
    }
    tip.hidden = true;
  };

  canvas.addEventListener("mousemove", onMove);
  canvas.addEventListener("mousedown", onDown);
  window.addEventListener("mouseup", onUp);
  canvas.addEventListener("mouseleave", onLeave);

  const ro = new ResizeObserver(resize);
  ro.observe(container);

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  resize();
  if (reduced) {
    // Same layout, no animation: settle it in one synchronous pass and paint the result.
    sim.stop();
    for (let i = 0; i < 320; i++) sim.tick();
    draw();
  } else {
    sim.on("tick", draw);
  }

  return () => {
    sim.on("tick", null);
    sim.stop();
    ro.disconnect();
    canvas.removeEventListener("mousemove", onMove);
    canvas.removeEventListener("mousedown", onDown);
    canvas.removeEventListener("mouseleave", onLeave);
    window.removeEventListener("mouseup", onUp);
  };
}

export const SUBGRAPH_LEGEND = [
  ["card_subject", "subject card"],
  ["transaction_flagged", "flagged txn"],
  ["device", "device"],
  ["card", "linked card"],
  ["prior_case", "prior case"],
];

export const legendColour = (key) => `var(${(STYLE[key] || STYLE.card)[1]})`;
