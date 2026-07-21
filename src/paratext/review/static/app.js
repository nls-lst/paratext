// paratext review UI. The pipeline emits a per-dataset
// view.json contract (GET /api/view) describing how to display and review a
// dataset: panels of fields (label + type), layout, scoring verdicts, and an
// optional flag control. This file renders generically from that contract and
// holds no per-schema knowledge.
// Keyboard: [f] flag (when a flag control exists), verdict hotkeys (1/2/3 by
//   default), [→] next, [←] previous, [Ctrl+s] save.

// ── Theme toggle ──────────────────────────────────────────────────────
// Oat sets `color-scheme: light dark`, so forcing colorScheme on the root
// switches every light-dark() token. Unset = follow the OS. The pre-paint
// script in index.html applies the stored value; this wires the button.
const themeToggle = document.getElementById("theme-toggle");
if (themeToggle) {
  const getTheme = () =>
    localStorage.getItem("theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  const applyTheme = (t) => {
    document.documentElement.style.colorScheme = t;
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("theme", t);
    themeToggle.textContent = t === "dark" ? "☀" : "☽";
  };

  applyTheme(getTheme());
  themeToggle.addEventListener("click", () => {
    applyTheme(getTheme() === "dark" ? "light" : "dark");
  });
}

const state = {
  datasets: [], // [{name, schema, count, base, round, active}]
  dataset: null, // current dataset name
  view: null, // the /api/view contract for state.viewDataset
  viewDataset: null, // which dataset state.view describes
  readOnly: false, // true when current dataset is an archived (non-active) round
  samples: [], // the working list: full list in review mode, filtered queue in eval mode
  allSamples: [], // unfiltered list (eval mode uses it for the header counts)
  samplesMode: null, // "review" | "eval" — so a mode switch reloads the working list
  index: 0,
  current: null,
  evalDirty: false, // an unsaved edit exists in the correction editor
};

// Fetch (and cache) the display/review contract for the current dataset.
async function ensureView() {
  if (state.view && state.viewDataset === state.dataset) return;
  const res = await fetch(api("api/view"));
  state.view = await res.json();
  state.viewDataset = state.dataset;
}

function groupDatasets(datasets) {
  const byBase = new Map();
  for (const d of datasets) {
    const g = byBase.get(d.base) ?? { base: d.base, schema: d.schema, rounds: [] };
    g.rounds.push(d);
    byBase.set(d.base, g);
  }
  for (const g of byBase.values()) {
    g.rounds.sort((a, b) => b.round - a.round);
    g.active = g.rounds[0];
    g.archived = g.rounds.slice(1);
  }
  return Array.from(byBase.values()).sort((a, b) => a.base.localeCompare(b.base));
}

function api(path, params = {}) {
  // Use a relative path so this works whether the app is served at the root
  // or behind a reverse-proxy prefix (e.g. /verify/). Building via `new URL`
  // with location.origin would strip that prefix.
  const qs = new URLSearchParams();
  if (state.dataset) qs.set("dataset", state.dataset);
  for (const [k, v] of Object.entries(params)) qs.set(k, v);
  const q = qs.toString();
  return q ? `${path}?${q}` : path;
}

async function loadDatasets() {
  const res = await fetch("api/datasets");
  state.datasets = await res.json();
}

function setDataset(name) {
  const d = state.datasets.find((d) => d.name === name);
  if (!d) {
    state.dataset = null;
    state.readOnly = false;
  } else {
    state.dataset = d.name;
    state.readOnly = d.active === false;
  }
  state.view = null;
  state.viewDataset = null;
  state.samples = [];
  state.allSamples = [];
  state.samplesMode = null;
  state.index = 0;
  state.current = null;
}

async function loadList(targetId = null) {
  const res = await fetch(api("api/samples"));
  state.samples = await res.json();
  state.samplesMode = "review";
  if (!state.samples.length) {
    document.getElementById("progress").textContent = "";
    document.getElementById("view").innerHTML = `
      <h2>${escapeHtml(state.view?.title ?? "Review")}</h2>
      <p class="muted">Nothing to review in this dataset — every record was filtered
        out during packaging (e.g. blank versos). Try another round from the picker.</p>
      <p><a href="#/select" class="button outline small">← Back to datasets</a></p>`;
    return;
  }
  if (targetId !== null) {
    const idx = state.samples.findIndex((s) => String(s.id) === String(targetId));
    if (idx !== -1) {
      state.index = idx;
      await loadSample();
      return;
    }
  }
  const firstUnannotated = state.samples.findIndex((s) => !s.annotated);
  state.index = firstUnannotated === -1 ? 0 : firstUnannotated;
  await loadSample();
}

async function loadSample() {
  const id = state.samples[state.index].id;
  const res = await fetch(api(`api/samples/${id}`));
  state.current = await res.json();
  clearTimeout(state.evalTimer);
  state.evalDirty = false;
  if (isEval()) renderEditor();
  else render();
}

function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  const scalar = (x) =>
    x !== null && typeof x === "object" ? JSON.stringify(x) : String(x);
  if (Array.isArray(v)) return v.length ? v.map(scalar).join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function fieldRow(obj, f) {
  return `
    <div class="field-row">
      <dt>${escapeHtml(f.label)}</dt>
      <dd>${escapeHtml(fmt(obj?.[f.key]))}</dd>
    </div>`;
}

// A <details> the reviewer opens on demand; omitted entirely when empty.
function collapsedBlock(obj, f) {
  const v = obj?.[f.key];
  if (v === null || v === undefined || v === "") return "";
  return `
    <details class="field-collapsed" style="margin:.5rem 0;">
      <summary>${escapeHtml(f.label)}</summary>
      <div style="margin:.4rem 0 .2rem .5rem; white-space:pre-wrap;">${escapeHtml(fmt(v))}</div>
    </details>`;
}

// Render a panel's body: scalar fields in a <dl>, then any "entries"
// (list-of-objects) fields as their own blocks, then any collapsed fields.
function panelBody(obj, fields) {
  const shown = fields.filter((f) => !f.collapsed);
  const scalar = shown.filter((f) => f.type !== "entries");
  const entries = shown.filter((f) => f.type === "entries");
  return `
    <dl>${scalar.map((f) => fieldRow(obj, f)).join("")}</dl>
    ${entries.map((f) => entriesBlock(f, obj?.[f.key])).join("")}
    ${fields.filter((f) => f.collapsed).map((f) => collapsedBlock(obj, f)).join("")}`;
}

function entriesBlock(field, entries) {
  if (!Array.isArray(entries) || !entries.length) {
    return `<p><em>No ${escapeHtml(field.label.toLowerCase())}.</em></p>`;
  }
  // Item columns come from the contract; fall back to the first row's keys.
  const items =
    field.item_fields ??
    Object.keys(entries[0] ?? {}).map((k) => ({ key: k, label: k }));
  return `
    <h4>${escapeHtml(field.label)} (${entries.length})</h4>
    <ol>
      ${entries
        .map(
          (e) => `
        <li>${items.map((it) => fieldRow(e, it)).join("")}</li>`,
        )
        .join("")}
    </ol>`;
}

function renderHeader() {
  const nav = document.querySelector("nav[data-topnav]");
  if (!nav) return;

  // Gate Review/Stats until a dataset is chosen — with no selection they just
  // fall back to the picker (looking like dead buttons).
  const gated = state.dataset ? "" : "none";
  for (const id of ["nav-review", "nav-stats"]) {
    const el = document.getElementById(id);
    if (el) el.style.display = gated;
  }

  // A project + round picker in the nav, so you can switch datasets without
  // returning to the homepage. Shown whenever there's more than one to pick.
  let host = document.getElementById("dataset-picker-host");
  if (!host) {
    host = document.createElement("span");
    host.id = "dataset-picker-host";
    nav.insertBefore(host, document.getElementById("progress"));
  }
  if (state.datasets.length <= 1) {
    host.innerHTML = "";
    return;
  }

  // Oat popover dropdown (ot-dropdown): a trigger button + a <menu popover>.
  // Menu items carry popovertargetaction="hide" so a click closes the popover
  // natively; the change listener handles selection.
  const MENU_ID = "nav-dataset-menu";
  const groups = groupDatasets(state.datasets);
  const roundLabel = (d) => `round ${d.round}${d.active === false ? " (archived)" : ""}`;
  const item = (d, label) =>
    `<button role="menuitem" class="ghost" data-dataset="${escapeHtml(d.name)}"
       popovertarget="${MENU_ID}" popovertargetaction="hide"
       style="display:block; width:100%; text-align:left;${
         d.name === state.dataset ? " font-weight:600;" : ""
       }">${d.name === state.dataset ? "✓ " : ""}${escapeHtml(label)}</button>`;

  const menuInner = groups
    .map((g, gi) => {
      const sep = gi > 0 ? "<hr>" : "";
      if (g.rounds.length === 1) return sep + item(g.rounds[0], g.base);
      const header = `<small role="presentation" style="display:block;
        padding:.25rem .75rem; color:var(--muted-foreground);">${escapeHtml(g.base)}</small>`;
      return sep + header + g.rounds.map((d) => item(d, roundLabel(d))).join("");
    })
    .join("");

  // Label the trigger with the current selection (or a prompt to choose).
  let triggerLabel = "Choose a project…";
  if (state.dataset) {
    const g = groups.find((g) => g.rounds.some((d) => d.name === state.dataset));
    const d = g?.rounds.find((d) => d.name === state.dataset);
    if (g && d) triggerLabel = g.rounds.length === 1 ? g.base : `${g.base} · ${roundLabel(d)}`;
  }

  host.innerHTML = `
    <ot-dropdown style="margin-left:.5rem;">
      <button popovertarget="${MENU_ID}" class="outline small"
              style="display:inline-flex; align-items:center; gap:.35rem;">
        ${escapeHtml(triggerLabel)}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      <menu popover id="${MENU_ID}">${menuInner}</menu>
    </ot-dropdown>`;

  host.querySelectorAll("[data-dataset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setDataset(btn.dataset.dataset);
      if (currentRoute() === "select") location.hash = "#/review";
      route();
    });
  });
}

function renderPicker() {
  document.getElementById("progress").textContent = "";
  if (!state.datasets.length) {
    document.getElementById("view").innerHTML =
      `<p>No datasets found. Run <code>paratext run -p &lt;project&gt;</code> to create a
         review round under <code>review/</code>, then reload — or point
         <code>paratext review</code> at a directory that contains one.</p>
    <p class="page-foot">
      <a href="#/projects">Project configuration</a> — the fields, prompt and
      source options each installed project runs with.
    </p>`;
    return;
  }

  const groups = groupDatasets(state.datasets);
  const cards = groups
    .map((g) => {
      const a = g.active;
      const roundTag = g.rounds.length > 1
        ? `<span style="color:var(--muted-foreground);"> · round ${a.round}</span>`
        : "";
      const archivedToggle = g.archived.length
        ? `<details style="margin:.25rem 0 .75rem 1rem;">
            <summary style="cursor:pointer; color:var(--muted-foreground); font-size:.875rem;">
              ↓ ${g.archived.length} previous round${g.archived.length === 1 ? "" : "s"}
            </summary>
            <div style="margin-top:.25rem;">${g.archived
              .map(
                (d) => `
                <button class="outline" data-dataset="${escapeHtml(d.name)}"
                        style="display:block; width:100%; text-align:left; padding:.5rem .75rem; margin-bottom:.25rem; opacity:.75;">
                  <strong>${escapeHtml(d.base)} · round ${d.round}</strong>
                  <small style="display:block; color:var(--muted-foreground);">
                    archived (read-only) · ${d.count} sample${d.count === 1 ? "" : "s"}
                  </small>
                </button>`,
              )
              .join("")}</div>
          </details>`
        : "";
      return `
        <div style="margin-bottom:.75rem;">
          <button class="primary" data-dataset="${escapeHtml(a.name)}"
                  style="display:block; width:100%; text-align:left; padding:1rem;">
            <strong>${escapeHtml(g.base)}${roundTag}</strong>
            <small style="display:block; opacity:.75;">
              ${escapeHtml(g.schema)} · ${a.count} sample${a.count === 1 ? "" : "s"}
            </small>
          </button>
          ${archivedToggle}
        </div>`;
    })
    .join("");

  // Projects lives here, not in the top nav: it's an orientation surface, not
  // part of the review loop, and a reviewer mid-round shouldn't be one stray
  // click from a page of schema internals.
  document.getElementById("view").innerHTML = `
    <h2>Choose a dataset to review</h2>
    <div style="max-width:32rem;">${cards}</div>
    <p class="page-foot">
      <a href="#/projects">Project configuration</a> — the fields, prompt and
      source options each installed project runs with.
    </p>
  `;
  document.querySelectorAll("[data-dataset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setDataset(btn.dataset.dataset);
      location.hash = "#/review";
      route();
    });
  });
}

// variant "thumbs" → small inline gallery (stacked layout); "media" → large
// images sized to their column (split layout).
function imagesHtml(s, variant) {
  return `<div class="${variant}">${s.images
    .map((p) => `<a href="${p}" target="_blank"><img src="${p}" alt="page" /></a>`)
    .join("")}</div>`;
}

function render() {
  const s = state.current;
  const a = s.annotation ?? {};
  const view = state.view;
  const remaining = state.samples.filter((x) => !x.annotated).length;
  document.getElementById("progress").innerHTML = `
    <span class="sample-label" title="${escapeHtml(String(s.document_id ?? s.id))}"
      >Sample ${state.index + 1} / ${state.samples.length} —
      ${escapeHtml(String(s.document_id ?? s.id))}</span>
    <button id="jump-next" class="outline small"
            ${remaining === 0 ? "disabled" : ""}>
      Next unchecked${remaining ? ` (${remaining})` : ""}
    </button>
  `;
  document.getElementById("jump-next")?.addEventListener("click", jumpToNextUnchecked);

  const detScore = s.deterministic_scores?.accuracy;
  const detBadge =
    detScore !== undefined
      ? `<p class="progress">Deterministic score: ${(detScore * 100).toFixed(0)}% — ${
          escapeHtml(s.deterministic_explanation ?? "")
        }</p>`
      : "";

  const panelsHtml = view.panels.map((p) => renderPanel(p, s, a)).join("");
  const heading = `<h2>${escapeHtml(view.title)} ${escapeHtml(String(s.document_id ?? s.id))}</h2>`;
  const atFirst = state.index === 0;
  const atLast = state.index === state.samples.length - 1;
  // At the end of the pass the primary CTA becomes a route to the stats summary,
  // rather than a Next button that silently no-ops.
  const nextControl = atLast
    ? `<a href="#/stats" class="button primary">Done — see stats →</a>`
    : `<button id="next" class="primary">Next →</button>`;
  const nav = `
    <div class="controls">
      <button id="prev"${atFirst ? " disabled" : ""}>← Previous</button>
      ${nextControl}
    </div>`;
  const readOnlyBanner = state.readOnly
    ? `<aside class="readonly-banner">
        This round is archived (read-only). Existing annotations are shown but cannot be changed.
        <a href="#/select">Switch round →</a>
      </aside>`
    : "";

  // Split layout: image beside the (single) model panel, nothing to scroll
  // past before scoring. Stacked: image on top, then the compare panes.
  const body =
    view.layout === "split"
      ? `<div class="split">
           <div class="split-media">${imagesHtml(s, "media")}</div>
           <div class="split-content">${panelsHtml}${notesForm(a)}${nav}</div>
         </div>`
      : `<section>${imagesHtml(s, "thumbs")}</section>${detBadge}${
          view.panels.length > 1 ? `<div class="panes">${panelsHtml}</div>` : panelsHtml
        }${notesForm(a)}${nav}`;

  document.getElementById("view").innerHTML = `
    <section>${heading}</section>
    ${readOnlyBanner}
    ${body}
  `;

  document.querySelectorAll("[data-scope]").forEach((btn) => {
    if (state.readOnly) {
      btn.disabled = true;
      btn.style.cursor = "not-allowed";
      return;
    }
    btn.addEventListener("click", async () => {
      await mark(btn.dataset.scope, btn.dataset.value);
      save();
    });
  });
  document.getElementById("prev").addEventListener("click", () => navigate(-1));
  document.getElementById("next")?.addEventListener("click", () => navigate(1));
  const form = document.getElementById("tweaks-form");
  if (form) {
    if (state.readOnly) {
      form.querySelectorAll("textarea, input").forEach((el) => (el.disabled = true));
    } else {
      let t;
      form.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(save, 400);
      });
    }
  }
}

// One panel from the contract, backed by s[panel.source] (model_output or
// ground_truth). The flag control (if any) and the verdict buttons (on the
// model panel) come from the contract too.
function renderPanel(panel, s, a) {
  const obj = s[panel.source] ?? {};
  const flagBtn = panel.flag
    ? `<div class="controls">
        <button data-scope="catalogue" data-value="${escapeHtml(panel.flag.value)}" class="${
          a.catalogue_correct === panel.flag.value ? "selected no" : ""
        }">${escapeHtml(panel.flag.label)} <span class="kbd">f</span></button>
      </div>`
    : "";
  const scoring = panel.source === "model_output" ? scoringButtons(a) : "";
  return `
    <div class="pane">
      <h3>${escapeHtml(panel.title)}</h3>
      ${panelBody(obj, panel.fields)}
      ${flagBtn}
      ${scoring}
    </div>`;
}

function scoringButtons(a) {
  return `
    <div class="controls">
      ${state.view.scoring.verdicts
        .map((v) => {
          const sel =
            a.model_correct === v.value ? (v.negative ? "selected no" : "selected") : "";
          return `<button data-scope="model" data-value="${escapeHtml(v.value)}" class="${sel}">${escapeHtml(
            v.label,
          )} <span class="kbd">${escapeHtml(v.hotkey)}</span></button>`;
        })
        .join("")}
    </div>`;
}

// Free-text notes, shown when the chosen verdict has notes:true in the contract.
function notesForm(a) {
  const { verdicts, notes } = state.view.scoring;
  const cur = verdicts.find((v) => v.value === a.model_correct);
  const show = cur?.notes === true;
  return `
    <form id="tweaks-form" ${show ? "" : "hidden"}>
      <label>${escapeHtml(notes.label)}
        <textarea name="notes" rows="3" placeholder="${escapeHtml(notes.placeholder)}">${escapeHtml(
          a.notes ?? "",
        )}</textarea>
      </label>
    </form>`;
}

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );
}

// Capture the notes textarea into state before a re-render throws the DOM away,
// so switching verdicts (or a verdict hotkey) mid-sentence doesn't lose the text.
function flushNotes() {
  const form = document.getElementById("tweaks-form");
  if (!form || form.hidden || !state.current) return;
  const a =
    state.current.annotation ??
    (state.current.annotation = { sample_id: String(state.current.id) });
  for (const [k, v] of new FormData(form).entries()) a[k] = String(v);
}

async function mark(scope, value) {
  flushNotes();
  const a = state.current.annotation ?? { sample_id: String(state.current.id) };
  if (scope === "catalogue")
    a.catalogue_correct = a.catalogue_correct === value ? null : value;
  if (scope === "model")
    a.model_correct = a.model_correct === value ? null : value;
  state.current.annotation = a;
  render();
}

async function save() {
  if (state.readOnly) return;
  flushNotes();
  const a = state.current.annotation ?? { sample_id: String(state.current.id) };
  const res = await fetch(api(`api/annotations/${state.current.id}`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(a),
  });
  const saved = await res.json();
  state.current.annotation = saved;
  // Only count this sample as reviewed if a model score was chosen — rows
  // can also be created by autosaving the notes textarea on navigate.
  state.samples[state.index].annotated = (saved?.model_correct ?? null) !== null;
}

async function navigate(delta) {
  if (isEval()) await flushGold();
  else await save();
  const next = state.index + delta;
  if (next < 0 || next >= state.samples.length) return;
  state.index = next;
  await loadSample();
}

async function jumpToNextUnchecked() {
  await save();
  const start = state.index;
  // Search forward, then wrap to the start.
  for (let i = 1; i <= state.samples.length; i++) {
    const idx = (start + i) % state.samples.length;
    if (!state.samples[idx].annotated) {
      state.index = idx;
      await loadSample();
      return;
    }
  }
}

document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
  if (currentRoute() !== "review" && currentRoute() !== "eval") return;
  // Navigation works in read-only and in the correction editor.
  if (e.key === "ArrowRight") return navigate(1);
  if (e.key === "ArrowLeft") return navigate(-1);
  // Verdict/flag hotkeys are review-only (the editor has no verdict buttons).
  if (isEval() || state.readOnly || !state.view) return;
  if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    return save();
  }
  // 'f' flags the catalogue panel, if the contract defines a flag control.
  const flagPanel = state.view.panels.find((p) => p.flag);
  if (e.key === "f" && flagPanel) return mark("catalogue", flagPanel.flag.value);
  // Verdict hotkeys come from the contract.
  const verdict = state.view.scoring.verdicts.find((v) => v.hotkey === e.key);
  if (verdict) mark("model", verdict.value);
});

// ── Build eval set (correction editor) ─────────────────────────────────
// Surfaces only the rows the model got wrong (needs_tweaks / not_accurate) and
// lets a reviewer edit the fields into a correct answer. A saved edit becomes a
// gold label (POST /api/gold) which `paratext export` ships alongside the
// already-verified good_enough rows. The model verdict is never changed here.
const EVAL_VERDICTS = ["needs_tweaks", "not_accurate"];

async function loadEvalList(targetId = null) {
  const res = await fetch(api("api/samples"));
  state.allSamples = await res.json();
  state.samples = state.allSamples.filter((s) => EVAL_VERDICTS.includes(s.model_correct));
  state.samplesMode = "eval";
  if (!state.samples.length) return renderEvalEmpty();
  let idx = 0;
  if (targetId !== null) {
    const i = state.samples.findIndex((s) => String(s.id) === String(targetId));
    if (i !== -1) idx = i;
  } else {
    const firstUncorrected = state.samples.findIndex((s) => !s.corrected);
    idx = firstUncorrected === -1 ? 0 : firstUncorrected;
  }
  state.index = idx;
  await loadSample();
}

function renderEvalEmpty() {
  document.getElementById("progress").textContent = "";
  const good = state.allSamples.filter((s) => s.model_correct === "good_enough").length;
  const reviewed = state.allSamples.filter((s) => s.model_correct).length;
  document.getElementById("view").innerHTML = `
    <h2>Build eval set</h2>
    <p class="muted">Nothing to correct — no rows are marked <em>needs tweaks</em> or
      <em>not accurate</em>. ${
        reviewed
          ? `${good} good-enough row${good === 1 ? "" : "s"} ${
              good === 1 ? "is" : "are"
            } already gold.`
          : "Score some rows in Review first."
      }</p>
    <p><a href="#/review" class="button outline small">← Back to review</a></p>`;
}

function evalHeader() {
  const total = state.allSamples.length;
  const good = state.allSamples.filter((s) => s.model_correct === "good_enough").length;
  const queue = state.samples.length;
  const corrected = state.samples.filter((s) => s.corrected).length;
  return `
    <div class="eval-head">
      <span class="pill">${corrected} / ${queue} corrected</span>
      <span class="pill">${good} good-enough (already gold)</span>
      <span class="pill">eval set so far: ${good + corrected} of ${total}</span>
    </div>`;
}

// Editable control for one field spec, prefilled with `value`. Shared by the
// top-level fields and (recursively) the item fields of an entries editor.
function fieldControl(f, value) {
  const key = escapeHtml(f.key);
  if (f.type === "bool") {
    return `<select data-field="${key}" data-type="bool">
      <option value="true" ${value === true ? "selected" : ""}>yes</option>
      <option value="false" ${value === true ? "" : "selected"}>no</option>
    </select>`;
  }
  if (f.type === "enum") {
    const blank = `<option value="" ${
      value == null || value === "" ? "selected" : ""
    }>—</option>`;
    const opts = (f.options ?? [])
      .map((o) => `<option ${String(value) === o ? "selected" : ""}>${escapeHtml(o)}</option>`)
      .join("");
    return `<select data-field="${key}" data-type="enum">${blank}${opts}</select>`;
  }
  if (f.type === "number") {
    return `<input type="number" data-field="${key}" data-type="number" value="${value ?? ""}" />`;
  }
  if (f.type === "list") {
    const text = Array.isArray(value) ? value.join("\n") : "";
    return `<textarea data-field="${key}" data-type="list" rows="2"
      placeholder="one per line">${escapeHtml(text)}</textarea>`;
  }
  if (f.type === "entries") return entriesEditor(f, Array.isArray(value) ? value : []);
  return `<textarea data-field="${key}" data-type="string" rows="2">${escapeHtml(
    value ?? "",
  )}</textarea>`;
}

function entriesEditor(f, entries) {
  const rows = entries.map((e) => entryRow(f, e)).join("");
  return `<div class="entries-editor" data-field="${escapeHtml(f.key)}">
    <div class="entry-rows">${rows}</div>
    <button type="button" class="outline small" data-add-entry>+ Add ${escapeHtml(
      f.label.toLowerCase(),
    )}</button>
  </div>`;
}

function entryRow(f, entry) {
  const inner = (f.item_fields ?? [])
    .map(
      (it) => `<label class="entry-field"><span>${escapeHtml(it.label)}</span>
      ${fieldControl(it, entry?.[it.key])}</label>`,
    )
    .join("");
  return `<fieldset class="entry-row">
    <div class="entry-grid">${inner}</div>
    <button type="button" class="ghost small" data-del-entry>Remove</button>
  </fieldset>`;
}

function modelPanelOf(view) {
  return view.panels.find((p) => p.source === "model_output") ?? view.panels[0];
}

function fieldSpec(key) {
  return modelPanelOf(state.view).fields.find((f) => f.key === key);
}

function renderEditor() {
  const s = state.current;
  const base = s.model_output ?? {};
  const prefill = s.gold?.output ?? base;
  const note = s.annotation?.notes;
  const total = state.samples.length;
  document.getElementById("progress").innerHTML =
    `<span class="sample-label" title="${escapeHtml(String(s.document_id ?? s.id))}"
      >Correcting ${state.index + 1} / ${total} — ${escapeHtml(
        String(s.document_id ?? s.id),
      )}</span>`;

  const fields = modelPanelOf(state.view)
    .fields.map((f) => {
      const hint =
        f.type === "entries" ? "" : `<small class="hint">model: ${escapeHtml(fmt(base[f.key]))}</small>`;
      return `<div class="edit-field" data-key="${escapeHtml(f.key)}" data-type="${escapeHtml(
        f.type,
      )}">
        <label class="k">${escapeHtml(f.label)}</label>
        <div>${fieldControl(f, prefill[f.key])}${hint}</div>
      </div>`;
    })
    .join("");

  const atFirst = state.index === 0;
  const atLast = state.index === total - 1;
  const readOnlyBanner = state.readOnly
    ? `<aside class="readonly-banner">This round is archived (read-only). Corrections can't be saved.
        <a href="#/select">Switch round →</a></aside>`
    : "";

  document.getElementById("view").innerHTML = `
    <section><h2>Build eval set ${s.gold ? goldBadgeHtml() : ""}</h2></section>
    ${evalHeader()}
    ${readOnlyBanner}
    <div class="split">
      <div class="split-media">
        ${imagesHtml(s, "media")}
        ${note ? `<p class="muted eval-note"><strong>Reviewer note:</strong> ${escapeHtml(note)}</p>` : ""}
      </div>
      <div class="split-content">
        <form id="editor">${fields}</form>
        <div class="controls">
          <button id="ev-prev" ${atFirst ? "disabled" : ""}>← Previous</button>
          <button id="ev-clear" class="outline" ${s.gold ? "" : "disabled"}>Clear correction</button>
          ${
            atLast
              ? `<a href="#/stats" class="button primary">Done — see stats →</a>`
              : `<button id="ev-next" class="primary">Save &amp; next →</button>`
          }
        </div>
      </div>
    </div>`;

  const editor = document.getElementById("editor");
  if (state.readOnly) {
    editor.querySelectorAll("input, textarea, select, button").forEach((el) => (el.disabled = true));
  } else {
    wireEditor(editor);
  }
  document.getElementById("ev-prev").addEventListener("click", () => navigate(-1));
  document.getElementById("ev-next")?.addEventListener("click", () => navigate(1));
  document.getElementById("ev-clear").addEventListener("click", clearGold);
}

function goldBadgeHtml() {
  return `<span class="gold-badge">✓ saved as gold</span>`;
}

function wireEditor(editor) {
  editor.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add-entry]");
    const del = e.target.closest("[data-del-entry]");
    if (add) {
      const wrap = add.closest(".edit-field");
      wrap.querySelector(".entry-rows").insertAdjacentHTML(
        "beforeend",
        entryRow(fieldSpec(wrap.dataset.key), {}),
      );
      markDirty();
    } else if (del) {
      del.closest(".entry-row").remove();
      markDirty();
    }
  });
  editor.addEventListener("input", () => {
    markDirty();
    clearTimeout(state.evalTimer);
    state.evalTimer = setTimeout(saveGold, 500);
  });
}

function markDirty() {
  state.evalDirty = true;
}

function readControl(el) {
  const t = el.dataset.type;
  if (t === "bool") return el.value === "true";
  if (t === "enum") return el.value === "" ? null : el.value;
  if (t === "number") return el.value === "" ? null : Number(el.value);
  if (t === "list") return el.value.split("\n").map((x) => x.trim()).filter(Boolean);
  return el.value.trim() === "" ? null : el.value; // string
}

// Read the editor form back into a full output object (all schema fields).
function collectEdits() {
  const editor = document.getElementById("editor");
  const out = {};
  editor.querySelectorAll(":scope > .edit-field").forEach((wrap) => {
    const key = wrap.dataset.key;
    if (wrap.dataset.type === "entries") {
      out[key] = [...wrap.querySelectorAll(".entry-row")].map((row) => {
        const obj = {};
        row.querySelectorAll("[data-field]").forEach((ctl) => {
          obj[ctl.dataset.field] = readControl(ctl);
        });
        return obj;
      });
    } else {
      const ctl = wrap.querySelector("[data-field]");
      out[key] = ctl ? readControl(ctl) : null;
    }
  });
  return out;
}

// Stable stringify (sorted keys) so change detection ignores key order.
function canon(v) {
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  if (v && typeof v === "object")
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canon(v[k]))
        .join(",") +
      "}"
    );
  return JSON.stringify(v ?? null);
}

async function saveGold() {
  if (state.readOnly || !state.current || !document.getElementById("editor")) return;
  const output = collectEdits();
  const base = state.current.model_output ?? {};
  const fields = Object.keys(output).filter((k) => canon(output[k]) !== canon(base[k]));
  const res = await fetch(api(`api/gold/${state.current.id}`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ output, fields }),
  });
  state.current.gold = await res.json();
  state.evalDirty = false;
  for (const list of [state.samples, state.allSamples]) {
    const q = list.find((x) => String(x.id) === String(state.current.id));
    if (q) q.corrected = true;
  }
  reflectGoldState();
}

// Update the gold badge / header / Clear button in place (no re-render, so the
// autosave never steals focus mid-typing).
function reflectGoldState() {
  const hasGold = !!state.current.gold;
  const h2 = document.querySelector("#view h2");
  let badge = document.querySelector(".gold-badge");
  if (hasGold && !badge && h2) h2.insertAdjacentHTML("beforeend", " " + goldBadgeHtml());
  if (!hasGold && badge) badge.remove();
  const clear = document.getElementById("ev-clear");
  if (clear) clear.disabled = !hasGold;
  const head = document.querySelector(".eval-head");
  if (head) head.outerHTML = evalHeader();
}

async function flushGold() {
  clearTimeout(state.evalTimer);
  if (state.evalDirty) await saveGold();
}

async function clearGold() {
  if (state.readOnly || !state.current) return;
  clearTimeout(state.evalTimer);
  await fetch(api(`api/gold/${state.current.id}`), { method: "DELETE" });
  state.current.gold = null;
  state.evalDirty = false;
  for (const list of [state.samples, state.allSamples]) {
    const q = list.find((x) => String(x.id) === String(state.current.id));
    if (q) q.corrected = false;
  }
  renderEditor();
}

// ── Stats view ────────────────────────────────────────────────────────
// LCS-based line diff. ~100 lines × 100 lines is trivial; no need for
// a Myers-style algorithm.
function lineDiff(oldText, newText) {
  const a = oldText.split("\n");
  const b = newText.split("\n");
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1] + 1
          : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  const out = [];
  let i = m;
  let j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      out.push({ t: "=", text: a[i - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      out.push({ t: "+", text: b[j - 1] });
      j--;
    } else {
      out.push({ t: "-", text: a[i - 1] });
      i--;
    }
  }
  return out.reverse();
}

function renderDiff(oldText, newText) {
  const lines = lineDiff(oldText, newText);
  const styles = {
    "+": "color:var(--success); background:color-mix(in srgb, var(--success) 10%, transparent);",
    "-": "color:var(--danger); background:color-mix(in srgb, var(--danger) 10%, transparent);",
    "=": "color:var(--muted-foreground);",
  };
  return lines
    .map(
      (l) =>
        `<div style="${styles[l.t]} padding:0 .5rem; white-space:pre-wrap;">${
          l.t === "=" ? " " : l.t
        } ${escapeHtml(l.text)}</div>`,
    )
    .join("");
}

function renderPromptsPanel(prompts) {
  if (!prompts.length) {
    return `<details style="margin:1rem 0;"><summary><strong>Prompt history</strong> <small style="color:var(--muted-foreground);">(no prompt text recorded)</small></summary></details>`;
  }
  const items = prompts
    .map(
      (p, i) => {
        const rounds = (p.rounds ?? []).length
          ? `round${p.rounds.length === 1 ? "" : "s"} ${p.rounds.join(", ")}`
          : "";
        const isLatest = i === 0;
        // Only the latest panel gets a diff toggle (diff vs the immediately
        // preceding prompt). Older panels are display-only.
        const previous = isLatest ? prompts[1] : null;
        const diffToggle = previous
          ? `<div style="margin-top:.5rem;">
              <button type="button" class="outline small" data-diff-against="${escapeHtml(previous.hash)}" data-diff-self="${escapeHtml(p.hash)}">
                Difference vs previous round
              </button>
            </div>`
          : "";
        return `
      <details ${isLatest ? "open" : ""} style="margin:.5rem 0;">
        <summary>
          <code>${escapeHtml(p.hash)}</code>
          <small style="color:var(--muted-foreground); margin-left:.5rem;">
            ${rounds ? escapeHtml(rounds) + " · " : ""}${p.count} record${p.count === 1 ? "" : "s"}${isLatest ? " · latest" : ""}
          </small>
        </summary>
        ${diffToggle}
        <div data-prompt-body="${escapeHtml(p.hash)}" style="margin-top:.5rem;">
          <pre style="white-space:pre-wrap; font-size:.8125rem; padding:.75rem; background:var(--muted); border-radius:.25rem; margin:0;">${escapeHtml(
            p.text,
          )}</pre>
        </div>
      </details>`;
      },
    )
    .join("");
  return `
    <details style="margin:1rem 0;">
      <summary><strong>Prompt history</strong> <small style="color:var(--muted-foreground);">(${prompts.length} version${prompts.length === 1 ? "" : "s"})</small></summary>
      <div style="margin-top:.5rem;">${items}</div>
    </details>
  `;
}

async function renderStats() {
  const [statsRes, tableRes, promptsRes] = await Promise.all([
    fetch(api("api/stats")),
    fetch(api("api/table")),
    fetch(api("api/prompts")),
  ]);
  const s = await statsRes.json();
  const rows = await tableRes.json();
  const promptsData = await promptsRes.json();
  document.getElementById("progress").textContent = "";

  const badge = (v) => {
    if (v === "good_enough") return `<span class="ok">Good enough</span>`;
    if (v === "needs_tweaks") return `<span class="warn">Needs tweaks</span>`;
    if (v === "not_accurate") return `<span class="bad">Not accurate</span>`;
    return `<span class="muted">—</span>`;
  };

  // Stats display is driven by the contract: which exports apply, whether a
  // flag count is meaningful, and the table column headers.
  const view = state.view;
  const hasFlag = view.panels.some((p) => p.flag);
  const tl = view.table_label;
  const titleHeader =
    (tl &&
      view.panels
        .find((p) => p.source === tl.source)
        ?.fields.find((f) => f.key === tl.key)?.label) ||
    "Title";
  const exportLinks = (view.exports ?? [])
    .map(
      (exp) =>
        `<a href="${api("api/export/" + exp.id)}" class="button outline small" download>${escapeHtml(
          exp.label,
        )}</a>`,
    )
    .join("");

  document.getElementById("view").innerHTML = `
    <h2>Stats — ${escapeHtml(s.dataset)} <small class="muted">(${escapeHtml(s.schema)})</small></h2>

    <dl>
      <div class="field-row"><dt>Reviewed</dt><dd>${s.annotated} of ${s.total} (${
        s.total ? ((s.annotated / s.total) * 100).toFixed(0) : 0
      }%)</dd></div>
      <div class="field-row"><dt>Accuracy score</dt><dd><strong>${
        s.model.accuracy !== null ? s.model.accuracy.toFixed(1) + "%" : "—"
      }</strong> <small>(good=1.0, tweaks=0.5, inaccurate=0 · ${s.model.scored} scored)</small></dd></div>
      <div class="field-row"><dt>Good enough</dt><dd class="ok">${s.model.good_enough}</dd></div>
      <div class="field-row"><dt>Needs tweaks</dt><dd class="warn">${s.model.needs_tweaks}</dd></div>
      <div class="field-row"><dt>Not accurate</dt><dd class="bad">${s.model.not_accurate}</dd></div>
      ${hasFlag ? `<div class="field-row"><dt>Flagged</dt><dd>${s.flagged_marc}</dd></div>` : ""}
      <div class="field-row"><dt>Eval gold set</dt><dd><strong>${s.eval_gold ?? s.model.good_enough}</strong>
        <small class="muted">(${s.model.good_enough} good-enough + ${s.corrected ?? 0} human-corrected ·
        <a href="#/eval">build →</a>)</small></dd></div>
    </dl>

    ${renderPromptsPanel(promptsData.prompts ?? [])}

    ${exportLinks ? `<div class="controls">${exportLinks}</div>` : ""}

    <div class="table">
    <table>
      <thead>
        <tr>
          <th>${escapeHtml(view.id_label ?? "ID")}</th>
          <th>${escapeHtml(titleHeader)}</th>
          <th class="score-col">Model score</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (r) => `
          <tr class="row-link" onclick="location.hash='#/review/${escapeHtml(r.sample_id)}'">
            <td><code>${escapeHtml(r.document_id ?? r.sample_id)}</code></td>
            <td>${escapeHtml(r.title ?? "—")}</td>
            <td>${badge(r.model_correct)}</td>
            <td class="note-cell">${r.notes ? escapeHtml(r.notes) : ""}</td>
          </tr>`,
          )
          .join("")}
      </tbody>
    </table>
    </div>
  `;

  // Wire up "Diff vs latest" toggles in the prompt history panel.
  const promptByHash = new Map(
    (promptsData.prompts ?? []).map((p) => [p.hash, p]),
  );
  document.querySelectorAll("[data-diff-against]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const selfHash = btn.dataset.diffSelf;
      const otherHash = btn.dataset.diffAgainst;
      const self = promptByHash.get(selfHash);
      const other = promptByHash.get(otherHash);
      const body = document.querySelector(`[data-prompt-body="${CSS.escape(selfHash)}"]`);
      if (!self || !other || !body) return;
      const showingDiff = btn.dataset.mode === "diff";
      if (showingDiff) {
        body.innerHTML = `<pre style="white-space:pre-wrap; font-size:.8125rem; padding:.75rem; background:var(--muted); border-radius:.25rem; margin:0;">${escapeHtml(
          self.text,
        )}</pre>`;
        btn.textContent = "Difference vs previous round";
        btn.dataset.mode = "full";
      } else {
        // Diff base = previous prompt; new = current. So +/- read as
        // "what was added/removed since the previous round".
        body.innerHTML = `<div style="font-size:.8125rem; padding:.5rem; background:var(--muted); border-radius:.25rem; font-family:var(--font-mono);">${renderDiff(
          other.text,
          self.text,
        )}</div>`;
        btn.textContent = "Show full text";
        btn.dataset.mode = "diff";
      }
    });
  });
}

// ── Projects (read-only inspector) ────────────────────────────────────
// Describes the *installed* projects. Read-only: editing a project means
// editing a Python package, and this server may be shared.
// Styling is Oat's (.card / .badge / .table); only grid layout is local.
function fieldTypeDetail(f) {
  if (f.options)
    return `<span class="text-light">{ ${f.options.map(escapeHtml).join(" | ")} }</span>`;
  if (f.item_fields)
    return `<span class="text-light">[ ${f.item_fields
      .map((i) => escapeHtml(i.key))
      .join(", ")} ]</span>`;
  return "";
}

// Audit is green almost always, so it reads as a pill. Only a failure earns
// detail — and then it earns all of it.
function auditPill(problems) {
  if (!problems.length) return `<span class="badge" data-variant="success">Audit ok</span>`;
  return `<span class="badge" data-variant="danger">Audit failed</span>
    <ul class="mt-2">${problems.map((a) => `<li class="bad">${escapeHtml(a)}</li>`).join("")}</ul>`;
}

function projectCard(p) {
  if (p.error) {
    return `<article class="card proj mb-4">
      <h3>${escapeHtml(p.name)}</h3>
      <p class="bad">Failed to load: ${escapeHtml(p.error)}</p>
    </article>`;
  }
  const ep = p.entry_point || {};
  const src = p.source || {};
  const srcOpts = Object.entries(src)
    .filter(([k]) => k !== "kind" && k !== "exts")
    .map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(String(v))}`)
    .join(", ");

  const fields = (p.view.panels || [])
    .flatMap((panel) => panel.fields || [])
    .map(
      (f) => `<tr>
        <td><code>${escapeHtml(f.key)}</code></td>
        <td>${escapeHtml(f.type)} ${fieldTypeDetail(f)}</td>
        <td class="text-light">${f.collapsed ? "collapsed" : ""}</td>
      </tr>`,
    )
    .join("");

  // One line per fact rather than a label/value grid — the labels were doing
  // less work than the space they took.
  const meta = [
    `<code>${escapeHtml(ep.value || "?")}</code>`,
    `${escapeHtml(ep.package || "")} ${escapeHtml(ep.version || "")}`.trim(),
    `${escapeHtml(src.kind || "custom")}${srcOpts ? ` (${srcOpts})` : ""}`,
    `images ${escapeHtml(String(p.images.max_size))}px q${escapeHtml(
      String(p.images.quality),
    )}`,
    `prompt <code>${escapeHtml(p.prompt_hash)}</code> · ${p.prompt.split("\n").length} lines`,
  ]
    .filter(Boolean)
    .join(" · ");

  const lr = p.latest_round;
  const roundLabel = (r) =>
    `round ${escapeHtml(String(r.round))}` +
    (r.prompt_hash ? ` <code>${escapeHtml(r.prompt_hash)}</code>` : "");
  let drift = "";
  if (lr && !lr.matches_installed) {
    drift = `<p class="bad mt-2"><strong>Prompt differs</strong> from ${roundLabel(lr)}
        (<code>${escapeHtml(lr.dataset)}</code>) — a new run will not reproduce it.</p>
      <details class="mt-2"><summary>Diff — ${roundLabel(lr)} → installed</summary>
        <div class="box mt-2" style="font-size:.8125rem;">${renderDiff(
          lr.prompt,
          p.prompt,
        )}</div>
      </details>`;
  } else if (lr) {
    drift = `<p class="text-light mt-2">Prompt matches ${roundLabel(lr)}.</p>`;
  }

  return `<article class="card proj mb-4">
    <h3>${escapeHtml(p.name)}
      <span class="badge outline">${escapeHtml(p.schema_version)}</span>
      ${auditPill(p.audit)}</h3>
    <p class="proj-meta text-light">${meta}</p>
    ${drift}
    <div class="table"><table><thead><tr><th>Field</th><th>Type</th><th></th></tr></thead>
      <tbody>${fields}</tbody></table></div>
    <details class="mt-4"><summary>Prompt</summary>
      <pre class="box prompt-text">${escapeHtml(p.prompt)}</pre></details>
  </article>`;
}

async function renderProjects() {
  const el = document.getElementById("view");
  el.innerHTML = `<p class="text-light">Loading projects…</p>`;
  let projects;
  try {
    // Relative path, no dataset param: this endpoint is about what's installed,
    // and the prefix must survive being served behind /verify/.
    const res = await fetch("api/projects");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    projects = await res.json();
  } catch (e) {
    el.innerHTML = `<p class="bad">Could not load projects: ${escapeHtml(String(e))}</p>`;
    return;
  }

  if (!projects.length) {
    el.innerHTML = `<h2>Project configuration</h2>
      <p>No projects installed. Scaffold one with <code>paratext new</code>.</p>`;
    return;
  }

  el.innerHTML = `<h2>Project configuration</h2>
    ${projects.map(projectCard).join("")}
    <p class="mt-4"><a href="#/select" class="button outline small">← Back to datasets</a></p>`;
}

// ── Routing ───────────────────────────────────────────────────────────
function currentRoute() {
  if (location.hash === "#/select") return "select";
  if (location.hash === "#/stats") return "stats";
  if (location.hash === "#/projects") return "projects";
  if (location.hash === "#/eval" || location.hash.startsWith("#/eval/")) return "eval";
  return "review";
}

function isEval() {
  return currentRoute() === "eval";
}

async function route() {
  if (!state.datasets.length) {
    await loadDatasets();
  }

  // Projects describes what's installed, not what's been run — so it must not
  // sit behind dataset selection (a fresh install has no datasets at all).
  if (currentRoute() === "projects") {
    renderHeader();
    await renderProjects();
    return;
  }

  // Resolve the current dataset:
  // - 0 datasets → handled by renderPicker (shows guidance).
  // - 1 dataset  → auto-select.
  // - 2+ datasets → always show the picker first (no persisted choice).
  if (!state.dataset && state.datasets.length === 1) {
    setDataset(state.datasets[0].name);
  }

  if (currentRoute() === "select" || !state.dataset) {
    renderHeader();
    renderPicker();
    return;
  }

  renderHeader();
  await ensureView();

  if (currentRoute() === "stats") {
    await renderStats();
    return;
  }

  if (currentRoute() === "eval") {
    const m = location.hash.match(/^#\/eval\/(.+)$/);
    const targetId = m ? m[1] : null;
    if (state.samplesMode !== "eval") {
      await loadEvalList(targetId);
    } else if (targetId) {
      const idx = state.samples.findIndex((s) => String(s.id) === String(targetId));
      if (idx !== -1) {
        state.index = idx;
        await loadSample();
      } else renderEditor();
    } else if (state.current) {
      renderEditor();
    } else {
      await loadEvalList(null);
    }
    return;
  }

  const match = location.hash.match(/^#\/review\/(.+)$/);
  const targetId = match ? match[1] : null;
  if (state.samplesMode !== "review" || !state.samples.length) {
    await loadList(targetId);
  } else if (targetId) {
    const idx = state.samples.findIndex((s) => String(s.id) === String(targetId));
    if (idx !== -1) {
      state.index = idx;
      await loadSample();
    } else render();
  } else {
    render();
  }
}

window.addEventListener("hashchange", route);
route();
