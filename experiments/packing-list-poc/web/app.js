/* Packing-List Pre-Fill POC — browser logic (plain JavaScript, no build step).
 *
 * Sections:
 *   1. State and small helpers
 *   2. API calls (local server only)
 *   3. Upload and processing
 *   4. Rendering the draft (fields, lists, items, packages, attention list)
 *   5. Editing and PO comparison (recalculated on the server from the EDITED draft)
 *   6. Evidence drawer
 *   7. Finish review (local POC action: validate, show summary, download TXT/PDF/DOCX)
 *
 * Document text is always inserted with textContent, never as HTML.
 */
"use strict";

/* ===================== 1. State and helpers ===================== */
const state = {
  health: { maxUploadMB: 25, timeoutSecondsPerAttempt: 600, maxAttempts: 2 },
  file: null,
  jobId: null,
  startedAt: 0,
  timer: null,
  poller: null,
  pollFailures: 0,
  original: null,   // draft exactly as extracted (never edited)
  draft: null,      // supplier's working copy
  acknowledged: new Set(),
  compareSeq: 0,
  compareTimer: null,
};

const LABELS = {
  shipDate: "Ship date", carrier: "Carrier", trackingNumbers: "Tracking numbers",
  shippedQuantity: "Shipped quantity", unitOfMeasure: "Unit of measure", lotNumbers: "Lot numbers",
  serialNumbers: "Serial numbers", items: "Item lines", sublots: "Sublots", packages: "Boxes",
};
const LIST_FIELDS = ["trackingNumbers", "lotNumbers", "serialNumbers"];
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const clone = (obj) => JSON.parse(JSON.stringify(obj));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function fmtNum(n) {
  if (n === null || n === undefined || n === "") return "";
  const x = Number(n);
  return Number.isFinite(x) ? String(Math.round(x * 1e6) / 1e6) : String(n);
}

function isEmpty(v) {
  return v === null || v === undefined || (typeof v === "string" && !v.trim()) || (Array.isArray(v) && !v.length);
}

function sameValue(a, b) {
  if (isEmpty(a) && isEmpty(b)) return true;
  if (Array.isArray(a) || Array.isArray(b)) return JSON.stringify(a || []) === JSON.stringify(b || []);
  const na = Number(a), nb = Number(b);
  if (a !== "" && b !== "" && Number.isFinite(na) && Number.isFinite(nb) && typeof a !== "boolean") return na === nb;
  return String(a ?? "").trim().toUpperCase() === String(b ?? "").trim().toUpperCase();
}

function issueKey(issue) { return `${issue.field}:${issue.code}`; }

function issuesFor(field) {
  const related = field === "shippedQuantity" ? ["shippedQuantity", "unitOfMeasure"] : [field];
  return (state.original?.fieldIssues || []).filter((i) => related.includes(i.field));
}

let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

/* ===================== 2. API ===================== */
async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new Error("Cannot reach the local server. Is ui_server.py still running?");
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error(body?.error?.message || `The server answered with status ${res.status}.`);
    err.status = res.status;
    throw err;
  }
  return body;
}

function postJSON(path, data) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

/* ===================== 3. Upload and processing ===================== */
function setView(view) {
  $("#upload-card").hidden = view !== "upload";
  $("#processing-card").hidden = view !== "processing";
  $("#error-card").hidden = view !== "error";
  $("#results").hidden = view !== "results";
}

function showUploadError(msg) {
  const box = $("#upload-error");
  box.textContent = msg;
  box.hidden = !msg;
}

function selectFile(file) {
  state.file = file || null;
  const label = $("#dz-file");
  if (!file) { label.hidden = true; return; }
  label.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  label.hidden = false;
  showUploadError("");
}

function readUploadPO() {
  return { quantity: $("#po-qty").value.trim(), unit: $("#po-unit").value.trim(), item: $("#po-item").value.trim() };
}

function validateUpload() {
  const f = state.file;
  if (!f) return "Please choose a PDF file first.";
  if (!/\.pdf$/i.test(f.name)) return "Only PDF files are supported in this POC. Images are planned for a later step.";
  if (f.size === 0) return "The selected file is empty.";
  if (f.size > state.health.maxUploadMB * 1024 * 1024) return `The file is larger than ${state.health.maxUploadMB} MB.`;
  const po = readUploadPO();
  if (po.quantity || po.unit || po.item) {
    const q = Number(po.quantity.replace(/,/g, ""));
    if (!po.quantity || !Number.isFinite(q) || q <= 0) return "PO quantity must be a number greater than zero (or leave all PO fields empty).";
    if (!po.unit) return "PO unit is required for a comparison (for example EA, PR or SF).";
  }
  return null;
}

async function startExtraction(event) {
  event.preventDefault();
  const problem = validateUpload();
  if (problem) { showUploadError(problem); return; }
  const btn = $("#extract-btn");
  btn.disabled = true;
  $("#file-input").disabled = true;
  try {
    $("#proc-file").textContent = state.file.name;
    $$(".steps li").forEach((li) => li.classList.remove("active", "done"));
    $("#step-upload").classList.add("active");
    state.startedAt = Date.now();
    tickTimer();
    state.timer = setInterval(tickTimer, 1000);
    setView("processing");
    const res = await api(`/api/jobs?filename=${encodeURIComponent(state.file.name)}`, {
      method: "POST", headers: { "Content-Type": "application/pdf" }, body: state.file,
    });
    state.jobId = res.jobId;
    $("#step-upload").classList.replace("active", "done");
    $("#step-convert").classList.add("active");
    state.pollFailures = 0;
    state.poller = setTimeout(pollJob, 1500);
  } catch (err) {
    stopProcessing();
    setView("upload");
    showUploadError(err.message);
  }
}

function tickTimer() {
  const s = Math.floor((Date.now() - state.startedAt) / 1000);
  $("#proc-elapsed").textContent = String(s);
  const perAttempt = state.health.timeoutSecondsPerAttempt;
  if (s > 180) {
    $("#proc-note").textContent = `Still working. This document is taking longer than usual. Each attempt may run up to ` +
      `${Math.round(perAttempt / 60)} minutes and the file is retried once if needed. Please keep this tab open.`;
  }
}

function stopProcessing() {
  clearInterval(state.timer);
  clearTimeout(state.poller);
  state.timer = state.poller = null;
  $("#extract-btn").disabled = false;
  $("#file-input").disabled = false;
}

async function pollJob() {
  let job;
  try {
    job = await api(`/api/jobs/${state.jobId}`);
    state.pollFailures = 0;
  } catch (err) {
    state.pollFailures += 1;
    if (state.pollFailures >= 5 || err.status === 404) {
      stopProcessing();
      showError({ message: err.message, advice: "Restart ui_server.py if it was closed, then upload the PDF again." });
      return;
    }
    state.poller = setTimeout(pollJob, 3000);
    return;
  }
  if (job.status === "running") {
    if (job.elapsedSeconds > 4) {
      $("#step-convert").classList.add("active");
    }
    state.poller = setTimeout(pollJob, 2000);
    return;
  }
  stopProcessing();
  if (job.status === "failed") { showError(job.error); return; }
  $$(".steps li").forEach((li) => { li.classList.remove("active"); li.classList.add("done"); });
  loadDraft(job.result, job.elapsedSeconds);
}

function showError(error) {
  setView("error");
  $("#error-title").textContent = error?.kind === "conversion_error" ? "The PDF could not be converted" : "Something went wrong";
  $("#error-message").textContent = error?.message || "Unknown error.";
  $("#error-advice").textContent = error?.advice || "";
  const list = $("#error-attempts");
  list.replaceChildren();
  const attempts = error?.attempts || [];
  for (const a of attempts) {
    list.append(el("li", { text: `Attempt ${a.attempt}: ${a.explanation} (${a.seconds ?? "?"} s)` }));
  }
  $("#error-details").hidden = attempts.length === 0;
}

/* ===================== 4. Rendering the draft ===================== */
function loadDraft(result, elapsed) {
  state.original = clone(result);
  state.draft = clone(result);
  state.acknowledged = new Set();
  const po = readUploadPO();
  $("#side-po-qty").value = po.quantity;
  $("#side-po-unit").value = po.unit;
  $("#side-po-item").value = po.item;
  const doc = result.document || {};
  $("#summary-line").textContent =
    `${result.sourceFile} · ${doc.pageCount ?? "?"} page(s)` +
    `${doc.ocrUsed ? " · scanned (OCR used)" : ""} · processed in ${Math.round(elapsed)} s`;
  setView("results");
  renderAll();
  scheduleCompare(0);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderAll() {
  renderScalarFields();
  LIST_FIELDS.forEach(renderList);
  renderItems();
  renderPackages();
  renderAttention();
  renderSummaryBadges();
}

function fieldBadges(field, currentValue) {
  const issues = issuesFor(field);
  const badges = [];
  const review = issues.filter((i) => i.severity === "review");
  if (review.length) {
    const allAck = review.every((i) => state.acknowledged.has(issueKey(i)));
    badges.push(el("span", { class: `badge ${allAck ? "ok" : "review"}`, text: allAck ? "Confirmed" : "Needs review" }));
  }
  if (isEmpty(currentValue)) badges.push(el("span", { class: "badge missing", text: "Missing" }));
  const orig = field === "shippedQuantity" ? state.original.shippedQuantity : state.original[field];
  if (!sameValue(orig, currentValue)) badges.push(el("span", { class: "badge edited", text: "Edited" }));
  else if (!isEmpty(currentValue) && !review.length) badges.push(el("span", { class: "badge ok", text: "Extracted" }));
  return { badges, needsReview: review.length > 0 && !review.every((i) => state.acknowledged.has(issueKey(i))) };
}

function decorateField(container, field, value) {
  const { badges, needsReview } = fieldBadges(field, value);
  $(".badges", container).replaceChildren(...badges);
  container.classList.toggle("needs-review", needsReview);
  container.classList.toggle("is-missing", isEmpty(value));
}

function renderScalarFields() {
  const d = state.draft;
  const raw = state.original.rawValues || {};
  $("#f-shipDate").value = d.shipDate ?? "";
  $("#f-carrier").value = d.carrier ?? "";
  $("#f-shippedQuantity").value = fmtNum(d.shippedQuantity);
  $("#f-unitOfMeasure").value = d.unitOfMeasure ?? "";
  const hasItems = (d.items || []).length > 0;
  $("#f-shippedQuantity").readOnly = hasItems;
  $("#f-unitOfMeasure").readOnly = hasItems;
  $("#f-shippedQuantity").title = hasItems ? "Calculated from the item lines below; edit the lines instead." : "";
  updateDateNote();
  setRaw("carrier", raw.carrier ? `As printed: ${raw.carrier}` : "");
  updateQtyNote();
  decorateField($('[data-field="shipDate"]'), "shipDate", d.shipDate);
  decorateField($('[data-field="carrier"]'), "carrier", d.carrier);
  decorateField($('[data-field="shippedQuantity"]'), "shippedQuantity", d.shippedQuantity);
}

/* Spell the date out ("7 February 2024") so the supplier sees exactly which day is meant,
   independent of the computer's locale. Returns null for an invalid date. */
function humanDate(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || "")) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return dt.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

function updateDateNote() {
  const raw = state.original.rawValues?.shipDate;
  const value = (state.draft.shipDate || "").trim();
  const parts = [];
  if (raw) parts.push(`As printed: ${raw}`);
  if (value) {
    const human = humanDate(value);
    parts.push(human ? `read as ${human}` : "use YYYY-MM-DD");
    $("#f-shipDate").classList.toggle("invalid", !human);
  } else {
    $("#f-shipDate").classList.remove("invalid");
  }
  setRaw("shipDate", parts.join(" · "));
}

function setRaw(field, text) {
  $(`[data-field="${field}"] .raw`).textContent = text;
}

function updateQtyNote(totalsMessage) {
  const hasItems = (state.draft.items || []).length > 0;
  let note = hasItems ? "Calculated from item lines." : "";
  if (totalsMessage) note = totalsMessage;
  $("#qty-note").textContent = note;
}

function renderList(field) {
  const box = $(`[data-field="${field}"]`);
  const ul = $(".chips", box);
  const values = state.draft[field] || [];
  const original = state.original[field] || [];
  ul.replaceChildren();
  if (!values.length) ul.append(el("li", { class: "none", text: "None" }));
  values.forEach((v, idx) => {
    ul.append(el("li", { class: original.includes(v) ? "" : "added" },
      v,
      el("button", { type: "button", "aria-label": `Remove ${v}`, title: "Remove", text: "×",
        onclick: () => { state.draft[field].splice(idx, 1); onEdited(); } })));
  });
  decorateField(box, field, values);
}

function addListValue(field) {
  const box = $(`[data-field="${field}"]`);
  const input = $(".add-row input", box);
  const value = input.value.trim().replace(/\s+/g, " ");
  if (!value) return;
  if (value.length > 60) { toast("That value is longer than 60 characters."); return; }
  state.draft[field] = state.draft[field] || [];
  if (state.draft[field].includes(value)) { toast("That value is already in the list."); return; }
  state.draft[field].push(value);
  input.value = "";
  onEdited();
}

function renderItems() {
  const items = state.draft.items || [];
  const body = $("#items-body");
  body.replaceChildren();
  $("#items-card").hidden = items.length === 0;
  const distinct = new Set(items.map((it) => (it.itemNumber || it.description || "").toUpperCase()));
  $("#items-note").textContent = items.length > 1
    ? `${items.length} line(s), ${distinct.size} different product(s). Quantities of different products or units are never added together.`
    : "Correct the shipped quantity or unit if the document was read incorrectly.";
  items.forEach((it, idx) => {
    const orig = state.original.items[idx] || {};
    const edited = !sameValue(orig.quantityShipped, it.quantityShipped) || !sameValue(orig.unitOfMeasure, it.unitOfMeasure);
    const qty = el("input", { type: "text", inputmode: "decimal", class: "qty", value: fmtNum(it.quantityShipped), name: `qty-${idx}`,
      "aria-label": `Shipped quantity, line ${idx + 1}` });
    qty.addEventListener("input", () => { it.quantityShipped = qty.value; onEdited(false); markRow(); });
    const unit = el("input", { type: "text", list: "unit-list", value: it.unitOfMeasure ?? "", placeholder: "—", name: `unit-${idx}`,
      "aria-label": `Unit, line ${idx + 1}` });
    unit.addEventListener("input", () => { it.unitOfMeasure = unit.value; onEdited(false); markRow(); });
    const ordered = it.quantityOrdered ?? it.quantityRequired;
    const outstanding = it.quantityOutstanding ?? it.quantityBackordered;
    const row = el("tr", { class: edited ? "edited" : "" },
      el("td", { text: it.lineNumber ?? String(idx + 1) }),
      el("td", { class: "desc" },
        it.itemNumber ? el("div", { class: "code", text: it.itemNumber }) : null,
        it.description ? el("div", { class: "text", text: it.description }) : null,
        it.customerItemNumber ? el("div", { class: "text muted", text: `Customer part ${it.customerItemNumber}` }) : null,
        (it.lots || []).length ? el("div", { class: "text muted", text: `Lots: ${it.lots.map((l) => l.lotNumber).join(", ")}` }) : null),
      el("td", { text: [it.salesOrder, it.customerReference].filter(Boolean).join(" / ") || "—" }),
      el("td", { class: "num", text: fmtNum(ordered) || "—" }),
      el("td", { class: "num" }, qty),
      el("td", {}, unit),
      el("td", { class: "num", text: fmtNum(outstanding) || "—" }),
      el("td", {}, el("button", { class: "link", type: "button", text: "Evidence", onclick: () => openEvidence("items", idx) })));
    function markRow() {
      const changed = !sameValue(orig.quantityShipped, it.quantityShipped) || !sameValue(orig.unitOfMeasure, it.unitOfMeasure);
      row.classList.toggle("edited", changed);
    }
    body.append(row);
  });
}

function renderPackages() {
  const pkgs = state.original.shippingDetails?.packages || [];
  $("#packages-card").hidden = pkgs.length === 0;
  $("#packages-body").replaceChildren(...pkgs.map((p) => el("tr", {},
    el("td", { text: p.packageNumber ?? "—" }),
    el("td", { class: "num", text: fmtNum(p.quantity) || "—" }),
    el("td", { class: "num", text: fmtNum(p.weight) || "—" }),
    el("td", { text: p.trackingNumber ?? "—" }),
    el("td", { text: p.page ?? "—" }))));
}

function attentionIssues() {
  const order = { review: 0, warning: 1 };
  return (state.original.fieldIssues || [])
    .filter((i) => i.severity === "review" || i.severity === "warning")
    .sort((a, b) => order[a.severity] - order[b.severity]);
}

function renderAttention() {
  const list = $("#attention-list");
  list.replaceChildren();
  const issues = attentionIssues();
  if (!issues.length) {
    list.append(el("li", { class: "confirmed" }, el("span", { text: "✓" }),
      el("div", { class: "msg" }, el("strong", { text: "Nothing flagged" }),
        el("span", { text: "Still check every value against the document before finishing." }))));
    return;
  }
  for (const issue of issues) {
    const isReview = issue.severity === "review";
    const key = issueKey(issue);
    const acked = state.acknowledged.has(key);
    let control;
    if (isReview) {
      const cb = el("input", { type: "checkbox", checked: acked, name: `ack-${key}`, "aria-label": `Confirm: ${issue.message}` });
      cb.addEventListener("change", () => {
        if (cb.checked) state.acknowledged.add(key); else state.acknowledged.delete(key);
        renderAttention(); renderScalarFields(); LIST_FIELDS.forEach(renderList); renderSummaryBadges();
      });
      control = el("label", { class: "ack" }, cb, acked ? "Checked" : "Mark checked");
    } else {
      control = el("span", { class: "badge missing", text: issue.code === "not_found" ? "Missing" : "Warning" });
    }
    const field = issue.field === "unitOfMeasure" ? "shippedQuantity" : issue.field;
    list.append(el("li", { class: isReview ? (acked ? "confirmed" : "review") : "missing" },
      control,
      el("div", { class: "msg" }, el("strong", { text: LABELS[issue.field] || issue.field }), el("span", { text: issue.message })),
      el("button", { class: "link", type: "button", text: "Evidence", onclick: () => openEvidence(field) })));
  }
}

function renderSummaryBadges() {
  const issues = attentionIssues();
  const review = issues.filter((i) => i.severity === "review");
  const open = review.filter((i) => !state.acknowledged.has(issueKey(i))).length;
  const missing = issues.filter((i) => i.code === "not_found").length;
  const badges = [];
  badges.push(el("span", { class: `badge ${open ? "review" : "ok"}`, text: open ? `${open} to review` : "All flagged values checked" }));
  if (missing) badges.push(el("span", { class: "badge missing", text: `${missing} not found` }));
  if (state.original.document?.ocrUsed) badges.push(el("span", { class: "badge missing", text: "OCR" }));
  $("#summary-badges").replaceChildren(...badges);
}

/* ===================== 5. Editing and PO comparison ===================== */
function onEdited(rerender = true) {
  if (rerender) renderAll(); else { renderSummaryBadges(); }
  scheduleCompare();
}

function currentPO() {
  return { quantity: $("#side-po-qty").value.trim(), unit: $("#side-po-unit").value.trim(), item: $("#side-po-item").value.trim() };
}

function scheduleCompare(delay = 350) {
  clearTimeout(state.compareTimer);
  state.compareTimer = setTimeout(runCompare, delay);
}

async function runCompare() {
  if (!state.draft) return;
  const seq = ++state.compareSeq;
  let res;
  try {
    res = await postJSON("/api/po-compare", { draft: state.draft, po: currentPO() });
  } catch (err) {
    if (seq === state.compareSeq) setPOStatus("invalid", "Comparison unavailable", err.message);
    return;
  }
  if (seq !== state.compareSeq) return;   // a newer edit is already being compared
  if ((state.draft.items || []).length) {
    state.draft.shippedQuantity = res.shippedQuantity;
    state.draft.unitOfMeasure = res.unitOfMeasure;
    $("#f-shippedQuantity").value = fmtNum(res.shippedQuantity);
    $("#f-unitOfMeasure").value = res.unitOfMeasure ?? "";
    decorateField($('[data-field="shippedQuantity"]'), "shippedQuantity", res.shippedQuantity);
  }
  updateQtyNote(res.totals?.message);
  renderPOResult(res);
}

function renderPOResult(res) {
  const poErrors = (res.errors || []).filter((e) => e.field.startsWith("po"));
  const valueErrors = (res.errors || []).filter((e) => !e.field.startsWith("po"));
  $("#side-po-qty").classList.toggle("invalid", poErrors.some((e) => e.field === "poQuantity"));
  $("#side-po-unit").classList.toggle("invalid", poErrors.some((e) => e.field === "poUnit"));
  $("#f-shippedQuantity").classList.toggle("invalid", valueErrors.some((e) => e.field === "shippedQuantity"));
  $$("#items-body input.qty").forEach((inp, idx) =>
    inp.classList.toggle("invalid", valueErrors.some((e) => e.field === `items[${idx}].quantityShipped`)));
  const issues = $("#po-issues");
  issues.replaceChildren();
  $("#po-numbers").hidden = true;
  if (poErrors.length || valueErrors.length) {
    setPOStatus("invalid", "Check the highlighted values", [...poErrors, ...valueErrors].map((e) => e.message).join(" "));
    return;
  }
  if (!res.poRequested || !res.comparison) {
    setPOStatus("neutral", "Not requested", "Enter a PO quantity and unit to compare.");
    return;
  }
  const c = res.comparison;
  const labels = {
    match: ["Matches the PO", "Shipped quantity equals the PO quantity."],
    over_shipped: ["Over-shipped", "More was shipped than the PO quantity."],
    under_shipped: ["Under-shipped", "Less was shipped than the PO quantity."],
    cannot_compare: ["Cannot compare", "A safe comparison is not possible with the current values."],
  };
  const [label, detail] = labels[c.status] || [c.status, ""];
  setPOStatus(c.status, label, detail);
  if (c.status !== "cannot_compare") {
    $("#po-shipped").textContent = `${fmtNum(c.shippedQuantity)} ${c.shippedUnit || ""}`.trim();
    $("#po-po").textContent = `${fmtNum(c.poQuantity)} ${c.poUnit || ""}`.trim();
    const diff = Number(c.difference);
    $("#po-diff").textContent = `${diff > 0 ? "+" : ""}${fmtNum(diff)} ${c.shippedUnit || ""}`.trim();
    $("#po-numbers").hidden = false;
  }
  for (const msg of c.issues || []) issues.append(el("li", { text: msg }));
}

function setPOStatus(kind, label, detail) {
  const box = $("#po-status");
  box.className = `po-status ${kind}`;
  $(".po-status-label", box).textContent = label;
  $(".po-status-detail", box).textContent = detail;
}

function bindEditors() {
  $("#f-shipDate").addEventListener("input", (e) => {
    state.draft.shipDate = e.target.value.trim() || null;
    updateDateNote();
    decorateField($('[data-field="shipDate"]'), "shipDate", state.draft.shipDate);
    renderSummaryBadges();
  });
  $("#f-carrier").addEventListener("input", (e) => {
    state.draft.carrier = e.target.value;
    decorateField($('[data-field="carrier"]'), "carrier", e.target.value);
    renderSummaryBadges();
  });
  $("#f-shippedQuantity").addEventListener("input", (e) => {
    if (e.target.readOnly) return;
    state.draft.shippedQuantity = e.target.value;
    decorateField($('[data-field="shippedQuantity"]'), "shippedQuantity", e.target.value);
    scheduleCompare();
  });
  $("#f-unitOfMeasure").addEventListener("input", (e) => {
    if (e.target.readOnly) return;
    state.draft.unitOfMeasure = e.target.value;
    scheduleCompare();
  });
  for (const field of LIST_FIELDS) {
    const box = $(`[data-field="${field}"]`);
    $(".add-btn", box).addEventListener("click", () => addListValue(field));
    $(".add-row input", box).addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addListValue(field); }
    });
  }
  ["#side-po-qty", "#side-po-unit", "#side-po-item"].forEach((id) => $(id).addEventListener("input", () => scheduleCompare()));
  $$(".field .evidence-btn, .list-field .evidence-btn").forEach((btn) => {
    btn.addEventListener("click", () => openEvidence(btn.closest("[data-field]").dataset.field));
  });
}

/* ===================== 6. Evidence drawer ===================== */
function openEvidence(field, itemIndex = null) {
  const o = state.original;
  let entries = [];
  let title = LABELS[field] || field;
  if (field === "items" && itemIndex !== null) {
    const it = o.items[itemIndex] || {};
    entries = it.evidence || [];
    title = `Line ${it.lineNumber ?? itemIndex + 1}${it.itemNumber ? ` · ${it.itemNumber}` : ""}`;
  } else {
    entries = (o.evidence || {})[field] || [];
    if (field === "shippedQuantity") entries = entries.concat((o.evidence || {}).unitOfMeasure || []);
  }
  $("#drawer-title").textContent = `Evidence · ${title}`;
  const issueBox = $("#drawer-issues");
  issueBox.replaceChildren(...(itemIndex === null ? issuesFor(field) : []).map((i) =>
    el("div", { class: `drawer-issue ${i.code === "not_found" ? "missing" : ""}`, text: i.message })));
  const list = $("#drawer-list");
  list.replaceChildren();
  if (!entries.length) {
    list.append(el("li", {}, el("div", { class: "src", text: "No evidence: this value was not found in the document. " +
      "If the document shows it, enter it manually." })));
  }
  for (const e of entries) {
    list.append(el("li", {},
      el("div", { class: "meta" }, el("span", { class: "page-badge", text: `Page ${e.page ?? "?"}` }), el("span", { text: e.rule || "" })),
      el("div", { class: "src", text: e.text || "" })));
  }
  $("#evidence-drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
  $("#drawer-close").focus();
}

function closeEvidence() {
  $("#evidence-drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
}

/* ===================== 7. Finish review (LOCAL POC) ===================== */
let lastReviewed = null;

async function finishReview() {
  const btn = $("#finish-btn");
  btn.disabled = true;
  try {
    const res = await postJSON("/api/review", {
      original: state.original, draft: state.draft, po: currentPO(), acknowledged: Array.from(state.acknowledged),
    });
    showFinishResult(res);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

function showFinishResult(res) {
  const errBox = $("#finish-errors");
  const warnBox = $("#finish-warnings");
  errBox.replaceChildren();
  warnBox.replaceChildren();
  if (!res.ok) {
    errBox.append(el("div", { class: "result-block errors" },
      el("strong", { text: "Please fix these before finishing:" }),
      el("ul", {}, ...res.errors.map((e) => el("li", { text: `${LABELS[e.field] || e.field}: ${e.message}` })))));
  } else {
    errBox.append(el("div", { class: "result-block success", text: "Review complete. The reviewed draft is ready to download." }));
  }
  if (res.warnings?.length) {
    warnBox.append(el("div", { class: "result-block warnings" },
      el("strong", { text: "Please note:" }),
      el("ul", {}, ...res.warnings.map((w) => el("li", { text: w.message })))));
  }
  // The structured reviewed JSON stays in memory only (for a later backend integration);
  // the supplier sees the readable summary built by the server from the same final values.
  lastReviewed = res.ok ? res.reviewed : null;
  $("#finish-summary-wrap").hidden = !res.ok;
  $("#finish-summary").replaceChildren(...(res.ok && res.summary ? renderShipmentSummary(res.summary) : []));
  $("#finish-dialog").showModal();
}

function renderShipmentSummary(s) {
  const NP = "Not provided";
  const value = (text) => el("dd", { class: text === NP ? "not-provided" : "", text });
  const rows = (pairs) => el("dl", { class: "summary-rows" }, ...pairs.flatMap(([k, v]) => [el("dt", { text: k }), value(v)]));
  const listValue = (values) => values.length
    ? el("dd", {}, el("ul", { class: "summary-chips" }, ...values.map((v) => el("li", { text: v }))))
    : value(NP);
  const section = (title, ...children) => el("section", { class: "summary-section" }, el("h4", { text: title }), ...children);

  const out = [
    el("div", { class: "summary-banner" }, el("strong", { text: s.banner }),
      el("span", { class: "muted small", text: `${s.sourceFile} · reviewed ${s.reviewedAt}` })),
    section("Shipment", rows(s.shipment),
      el("dl", { class: "summary-rows" }, ...s.lists.flatMap(([k, v]) => [el("dt", { text: k }), listValue(v)]))),
  ];
  const items = s.items.length
    ? el("div", { class: "table-wrap" }, el("table", { class: "items summary-items" },
        el("thead", {}, el("tr", {}, ...["Line", "Item", "Description", "Shipped", "Lot numbers", "Serial numbers"]
          .map((h) => el("th", { text: h })))),
        el("tbody", {}, ...s.items.map((it) => el("tr", {},
          ...[it.line, it.item, it.description, it.shipped, it.lots, it.serials]
            .map((t) => el("td", { class: t === NP ? "not-provided" : "", text: t })))))))
    : el("p", { class: "not-provided", text: NP });
  out.push(section("Item lines", items));
  out.push(section("PO result", s.po ? rows(s.po) : el("p", { class: "not-provided", text: NP })));
  out.push(section("Review notes", s.notes.length
    ? el("ul", { class: "summary-notes" }, ...s.notes.map((n) => el("li", { text: n })))
    : el("p", { class: "muted", text: "None" })));
  return out;
}

async function downloadExport(btn) {
  if (!lastReviewed) return;
  const format = btn.dataset.format;
  btn.disabled = true;
  try {
    let res;
    try {
      res = await fetch(`/api/export?format=${format}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reviewed: lastReviewed }),
      });
    } catch {
      throw new Error("Cannot reach the local server. Is ui_server.py still running?");
    }
    if (!res.ok) {
      let msg = `The server answered with status ${res.status}.`;
      try { msg = (await res.json()).error.message || msg; } catch { /* keep default */ }
      throw new Error(msg);
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `reviewed-draft.${format}`;
    const a = el("a", { href: URL.createObjectURL(await res.blob()), download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast(`${format.toUpperCase()} downloaded.`);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ===================== Wiring ===================== */
function resetToUpload() {
  state.original = state.draft = null;
  state.jobId = null;
  selectFile(null);
  $("#file-input").value = "";
  showUploadError("");
  setView("upload");
}

function hasEdits() {
  if (!state.original) return false;
  return JSON.stringify(state.original) !== JSON.stringify(state.draft) || state.acknowledged.size > 0;
}

async function init() {
  try {
    state.health = await api("/api/health");
    $("#dz-hint").textContent = `PDF only · up to ${state.health.maxUploadMB} MB`;
  } catch (err) {
    showUploadError(err.message);
  }
  const input = $("#file-input");
  input.addEventListener("change", () => selectFile(input.files[0]));
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
  dz.addEventListener("drop", (e) => {
    if (input.disabled) return;
    const file = e.dataTransfer.files[0];
    if (file) selectFile(file);
  });
  $("#upload-form").addEventListener("submit", startExtraction);
  $("#error-retry").addEventListener("click", resetToUpload);
  $("#new-btn").addEventListener("click", () => {
    if (hasEdits() && !window.confirm("Discard your edits and upload another PDF?")) return;
    resetToUpload();
  });
  $("#finish-btn").addEventListener("click", finishReview);
  $("#finish-close").addEventListener("click", () => $("#finish-dialog").close());
  $$(".export-btn").forEach((btn) => btn.addEventListener("click", () => downloadExport(btn)));
  $("#drawer-close").addEventListener("click", closeEvidence);
  $("#drawer-backdrop").addEventListener("click", closeEvidence);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#evidence-drawer").hidden) closeEvidence(); });
  window.addEventListener("beforeunload", (e) => {
    if (state.timer || hasEdits()) { e.preventDefault(); e.returnValue = ""; }
  });
  bindEditors();
}

init();
