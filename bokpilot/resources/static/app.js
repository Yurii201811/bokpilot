const state = {
  workspace: null,
  selectedId: null,
  statusFilter: "all",
};

const formatter = new Intl.NumberFormat("sv-SE", {
  style: "currency",
  currency: "SEK",
});

const percentFormatter = new Intl.NumberFormat("sv-SE", {
  style: "percent",
  maximumFractionDigits: 0,
});

const els = {
  loadSample: document.querySelector("#load-sample"),
  reset: document.querySelector("#reset"),
  fileForm: document.querySelector("#file-form"),
  fileInput: document.querySelector("#file-input"),
  manualForm: document.querySelector("#manual-form"),
  manualDate: document.querySelector("#manual-date"),
  statusFilter: document.querySelector("#status-filter"),
  table: document.querySelector("#items-table"),
  empty: document.querySelector("#detail-empty"),
  detail: document.querySelector("#detail-content"),
  exportPreview: document.querySelector("#export-preview"),
  toast: document.querySelector("#toast"),
  reviewForm: document.querySelector("#review-form"),
};

els.manualDate.valueAsDate = new Date();

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("Content-Type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(payload.error || payload || "Request failed");
  }
  return payload;
}

async function refresh() {
  state.workspace = await request("/api/workspace");
  if (!state.selectedId && state.workspace.items.length > 0) {
    state.selectedId = state.workspace.items[0].id;
  }
  render();
}

function render() {
  renderMetrics();
  renderTable();
  renderDetail();
}

function renderMetrics() {
  const summary = state.workspace?.summary || {};
  document.querySelector("#metric-pending").textContent = summary.total_items || 0;
  document.querySelector("#metric-review").textContent = summary.needs_review || 0;
  document.querySelector("#metric-approved").textContent = summary.approved || 0;
  document.querySelector("#metric-export").textContent = summary.export_ready || 0;
}

function renderTable() {
  const items = filteredItems();
  els.table.replaceChildren(
    ...items.map((item) => {
      const raw = item.raw;
      const suggestion = item.suggestion;
      const row = document.createElement("tr");
      row.classList.toggle("selected", item.id === state.selectedId);
      row.tabIndex = 0;
      row.addEventListener("click", () => selectItem(item.id));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectItem(item.id);
        }
      });
      row.innerHTML = `
        <td><strong>${escapeHtml(item.id)}</strong></td>
        <td>${escapeHtml(raw.date)}</td>
        <td>${escapeHtml(raw.description)}</td>
        <td class="${Number(raw.amount) < 0 ? "amount-negative" : "amount-positive"}">${formatter.format(Number(raw.amount))}</td>
        <td>${escapeHtml(suggestion.bas_account)} ${escapeHtml(suggestion.bas_account_name)}</td>
        <td>${escapeHtml(String(suggestion.vat_rate))}%</td>
        <td><span class="confidence ${Number(suggestion.confidence) < 0.7 ? "low" : ""}">${percentFormatter.format(Number(suggestion.confidence))}</span></td>
        <td><span class="status-pill ${escapeHtml(item.status)}">${statusLabel(item.status)}</span></td>
      `;
      return row;
    })
  );
}

function renderDetail() {
  const item = selectedItem();
  els.empty.hidden = Boolean(item);
  els.detail.hidden = !item;
  if (!item) return;

  const raw = item.raw;
  const suggestion = item.suggestion;
  document.querySelector("#detail-id").textContent = item.id;
  document.querySelector("#detail-title").textContent = raw.description;
  document.querySelector("#detail-status").textContent = statusLabel(item.status);
  document.querySelector("#detail-status").className = `status-pill ${item.status}`;
  document.querySelector("#detail-amount").textContent = formatter.format(Number(raw.amount));
  document.querySelector("#detail-bas").textContent = `${suggestion.bas_account} ${suggestion.bas_account_name}`;
  document.querySelector("#detail-vat").textContent = `${suggestion.vat_rate}% (${formatter.format(Number(suggestion.vat_amount))})`;
  document.querySelector("#detail-confidence").textContent = percentFormatter.format(Number(suggestion.confidence));
  document.querySelector("#detail-explanation").textContent = suggestion.explanation;
  document.querySelector("#review-account").value = suggestion.bas_account;
  document.querySelector("#review-vat").value = String(Number(suggestion.vat_rate));
  document.querySelector("#review-note").value = item.reviewer_note || "";

  const riskList = document.querySelector("#risk-list");
  riskList.replaceChildren(
    ...(suggestion.risk_flags || []).map((flag) => {
      const li = document.createElement("li");
      li.textContent = flag;
      return li;
    })
  );

  const lines = document.querySelector("#journal-lines");
  lines.replaceChildren(
    ...suggestion.journal_lines.map((line) => {
      const div = document.createElement("div");
      div.className = "journal-line";
      div.innerHTML = `
        <div>
          <strong>${escapeHtml(line.account)} ${escapeHtml(line.account_name)}</strong>
          <span>${Number(line.debit) > 0 ? "Debit" : "Credit"}</span>
        </div>
        <span>${Number(line.debit) > 0 ? formatter.format(Number(line.debit)) : ""}</span>
        <span>${Number(line.credit) > 0 ? formatter.format(Number(line.credit)) : ""}</span>
      `;
      return div;
    })
  );
}

function filteredItems() {
  const items = state.workspace?.items || [];
  if (state.statusFilter === "all") return items;
  return items.filter((item) => item.status === state.statusFilter);
}

function selectedItem() {
  return (state.workspace?.items || []).find((item) => item.id === state.selectedId);
}

function selectItem(itemId) {
  state.selectedId = itemId;
  render();
}

function statusLabel(status) {
  return {
    needs_review: "Needs review",
    approved: "Approved",
    rejected: "Rejected",
  }[status] || status;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  window.setTimeout(() => els.toast.classList.remove("show"), 2600);
}

els.loadSample.addEventListener("click", async () => {
  state.workspace = await request("/api/load-sample", { method: "POST", body: "{}" });
  state.selectedId = state.workspace.items[0]?.id || null;
  toast("Sample Swedish bookkeeping scenarios loaded.");
  render();
});

els.reset.addEventListener("click", async () => {
  state.workspace = await request("/api/reset", { method: "POST", body: "{}" });
  state.selectedId = null;
  els.exportPreview.textContent = "Approve at least one item to preview an export.";
  toast("Workspace reset.");
  render();
});

els.statusFilter.addEventListener("change", () => {
  state.statusFilter = els.statusFilter.value;
  renderTable();
});

els.fileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = els.fileInput.files[0];
  if (!file) {
    toast("Choose a file first.");
    return;
  }
  const content = await file.text();
  const endpoint = file.name.toLowerCase().endsWith(".csv") ? "/api/import/bank-csv" : "/api/import/document";
  state.workspace = await request(endpoint, {
    method: "POST",
    body: JSON.stringify({ filename: file.name, content, kind: endpoint.includes("document") ? "document" : "bank_csv" }),
  });
  state.selectedId = state.workspace.items.at(-1)?.id || state.selectedId;
  els.fileForm.reset();
  toast(`${file.name} imported.`);
  render();
});

els.manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(els.manualForm).entries());
  state.workspace = await request("/api/import/manual", {
    method: "POST",
    body: JSON.stringify(data),
  });
  state.selectedId = state.workspace.items.at(-1)?.id || state.selectedId;
  els.manualForm.reset();
  els.manualDate.valueAsDate = new Date();
  toast("Manual transaction added.");
  render();
});

els.reviewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitter = event.submitter;
  const item = selectedItem();
  if (!item) return;
  const data = Object.fromEntries(new FormData(els.reviewForm).entries());
  data.status = submitter?.dataset.status || "needs_review";
  state.workspace = await request(`/api/items/${item.id}/review`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  toast(`${item.id} marked ${statusLabel(data.status).toLowerCase()}.`);
  render();
});

document.querySelectorAll("[data-export]").forEach((button) => {
  button.addEventListener("click", async () => {
    const type = button.dataset.export;
    const response = await fetch(`/api/export/${type}`);
    const payload = await response.text();
    if (!response.ok) {
      throw new Error(payload || "Export failed");
    }
    els.exportPreview.textContent = payload.trim() || "No approved items are ready for export.";
    toast(`${button.textContent} generated from approved items.`);
  });
});

refresh().catch((error) => {
  els.exportPreview.textContent = error.message;
  toast(error.message);
});
