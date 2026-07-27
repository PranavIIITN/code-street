const API_BASE = "http://localhost:8000";

const GATES = [
  { id: "g1", label: "G1", name: "Kill Switch" },
  { id: "g2", label: "G2", name: "Revocation" },
  { id: "g3", label: "G3", name: "Authorization" },
  { id: "g4", label: "G4", name: "Spend Cap" },
];

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json();
};

const postJson = (path, body) => request(path, {
  method: "POST",
  body: JSON.stringify(body),
});

function classifyGate(reason = "", decision = "") {
  const text = reason.toLowerCase();
  if (decision === "allowed" || text === "policy checks passed") {
    return { failedIndex: null, detail: "all gates passed" };
  }
  if (text.includes("emergency stop")) {
    return { failedIndex: 0, detail: "Gate 1 (Kill Switch)" };
  }
  if (text.includes("has been revoked")) {
    return { failedIndex: 1, detail: "Gate 2 (Revocation)" };
  }
  if (text.includes("not in") || text.includes("permitted actions")) {
    return { failedIndex: 2, detail: "Gate 3 (Authorization)" };
  }
  if (text.includes("exceeds per-transaction cap")) {
    return { failedIndex: 3, detail: "Gate 4a (Per-Txn Cap)" };
  }
  if (text.includes("would exceed fleet-wide")) {
    return { failedIndex: 3, detail: "Gate 4c (Fleet Cap)" };
  }
  if (text.includes("would exceed") && text.includes("daily cap")) {
    return { failedIndex: 3, detail: "Gate 4b (Daily Cap)" };
  }
  return { failedIndex: 3, detail: "Gate 4 (Governance)" };
}

function createPipeline(reason, decision) {
  const { failedIndex, detail } = classifyGate(reason, decision);
  const pipeline = document.createElement("span");
  pipeline.className = "gate-pipeline";
  pipeline.title = detail;

  GATES.forEach((gate, index) => {
    const chip = document.createElement("span");
    chip.className = "gate-chip";
    chip.textContent = failedIndex === null || index < failedIndex
      ? `${gate.label} ✓`
      : index === failedIndex
        ? `${gate.label} ✗`
        : `${gate.label} •`;
    chip.title = gate.name;

    if (failedIndex === null || index < failedIndex) {
      chip.classList.add("gate-chip--passed");
    } else if (index === failedIndex) {
      chip.classList.add("gate-chip--failed");
    } else {
      chip.classList.add("gate-chip--pending");
    }

    pipeline.appendChild(chip);
  });

  return pipeline;
}

function enhanceLiveFeedRows() {
  document.querySelectorAll(".live-feed-item").forEach((row) => {
    if (row.querySelector(".gate-pipeline")) return;
    const decisionEl = row.querySelector(".live-feed-decision");
    const reasonEl = row.querySelector(".live-feed-reason");
    if (!decisionEl || !reasonEl) return;

    const decision = decisionEl.textContent.trim().toLowerCase();
    const reason = reasonEl.getAttribute("title") || reasonEl.textContent;
    decisionEl.insertAdjacentElement("afterend", createPipeline(reason, decision));
  });
}

function enhanceAuditRows() {
  const header = document.querySelector(".audit-log-table thead tr");
  if (header && !header.querySelector(".audit-log-gates-heading")) {
    const th = document.createElement("th");
    th.className = "audit-log-gates-heading";
    th.textContent = "Gates";
    const reasonHeading = Array.from(header.children).find((cell) => (
      cell.textContent.trim().toLowerCase() === "reason"
    ));
    header.insertBefore(th, reasonHeading || null);
  }

  document.querySelectorAll(".audit-log-row").forEach((row) => {
    if (row.querySelector(".audit-log-gates")) return;
    const decisionEl = row.querySelector(".audit-log-decision");
    const reasonEl = row.querySelector(".audit-log-reason");
    if (!decisionEl || !reasonEl) return;

    const decision = decisionEl.textContent.trim().toLowerCase();
    const reason = reasonEl.getAttribute("title") || reasonEl.textContent;
    const td = document.createElement("td");
    td.className = "audit-log-gates";
    td.appendChild(createPipeline(reason, decision));
    row.insertBefore(td, reasonEl.closest("td"));
  });
}

function enhanceGateTransparency() {
  enhanceLiveFeedRows();
  enhanceAuditRows();
}

function hardenAttackButtonCooldown() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".attack-btn");
    if (!button || button.dataset.coolingDown === "true") return;

    button.dataset.coolingDown = "true";
    button.disabled = true;
    setTimeout(() => {
      button.dataset.coolingDown = "false";
      button.disabled = false;
    }, 2000);
  }, true);
}

function formatJson(value) {
  if (value == null) return "none";
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function createPolicyEditor() {
  if (document.querySelector(".policy-editor")) return;

  const agentsSection = Array.from(document.querySelectorAll(".section")).find((section) => (
    section.querySelector(".agent-grid")
  ));
  if (!agentsSection) return;

  const section = document.createElement("section");
  section.className = "section policy-editor";
  section.innerHTML = `
    <div class="section-label">Policy Editor</div>
    <div class="policy-editor-panel">
      <div class="policy-editor-form">
        <input
          class="policy-editor-input"
          type="text"
          placeholder="Describe a policy change in plain English…"
          autocomplete="off"
        />
        <button class="policy-editor-preview" type="button">Preview Change</button>
      </div>
      <div class="policy-editor-status" aria-live="polite"></div>
      <div class="policy-editor-result"></div>
      <div class="recent-policy-changes">
        <div class="recent-policy-title">Recent Policy Changes</div>
        <div class="recent-policy-list">No policy changes yet</div>
      </div>
    </div>
  `;

  agentsSection.insertAdjacentElement("afterend", section);

  const input = section.querySelector(".policy-editor-input");
  const previewButton = section.querySelector(".policy-editor-preview");
  const status = section.querySelector(".policy-editor-status");
  const result = section.querySelector(".policy-editor-result");

  let parsed = null;

  function setStatus(message, kind = "") {
    status.textContent = message;
    status.className = `policy-editor-status ${kind ? `policy-editor-status--${kind}` : ""}`;
  }

  function renderWarning(message) {
    result.innerHTML = `<div class="policy-warning">${escapeHtml(message)}</div>`;
  }

  function renderDiff(response, instruction) {
    const before = escapeHtml(formatJson(response.before));
    const after = escapeHtml(formatJson(response.after));
    const preview = escapeHtml(
      response.preview || response.diff?.explanation || "Policy change preview",
    );
    result.innerHTML = `
      <div class="policy-diff-card">
        <div class="policy-diff-preview">${preview}</div>
        <div class="policy-diff-grid">
          <div>
            <div class="policy-diff-label">Before</div>
            <pre class="policy-diff-code">${before}</pre>
          </div>
          <div>
            <div class="policy-diff-label">After</div>
            <pre class="policy-diff-code">${after}</pre>
          </div>
        </div>
        <button class="policy-editor-apply" type="button">Confirm & Apply</button>
      </div>
    `;
    result.querySelector(".policy-editor-apply").addEventListener("click", async () => {
      const applyButton = result.querySelector(".policy-editor-apply");
      applyButton.disabled = true;
      applyButton.textContent = "Applying…";
      setStatus("", "");
      try {
        await postJson("/policy/apply", {
          confirmed: true,
          instruction,
          diff: response.diff,
        });
        parsed = null;
        input.value = "";
        result.innerHTML = "";
        setStatus("Policy change applied.", "success");
        setTimeout(() => setStatus("", ""), 2500);
      } catch (error) {
        applyButton.disabled = false;
        applyButton.textContent = "Confirm & Apply";
        setStatus(error.message, "error");
      }
    });
  }

  previewButton.addEventListener("click", async () => {
    const instruction = input.value.trim();
    if (!instruction) {
      setStatus("Enter a policy change first.", "error");
      result.innerHTML = "";
      return;
    }

    parsed = null;
    previewButton.disabled = true;
    previewButton.textContent = "Previewing…";
    setStatus("", "");
    result.innerHTML = "";

    try {
      const response = await postJson("/policy/parse", { instruction });
      parsed = { response, instruction };
      if (response.applicable === false || response.warning) {
        renderWarning(response.warning || "This change cannot be applied safely.");
      } else {
        renderDiff(response, instruction);
      }
    } catch (error) {
      renderWarning(error.message);
    } finally {
      previewButton.disabled = false;
      previewButton.textContent = "Preview Change";
    }
  });

  input.addEventListener("input", () => {
    if (!parsed) return;
    parsed = null;
    result.innerHTML = "";
    setStatus("", "");
  });
}

function updateRecentPolicyChanges() {
  const list = document.querySelector(".recent-policy-list");
  if (!list) return;

  const rows = Array.from(document.querySelectorAll(".audit-log-row"))
    .map((row) => {
      const cells = row.querySelectorAll("td");
      return {
        time: cells[0]?.textContent.trim(),
        agent: cells[1]?.textContent.trim(),
        action: cells[2]?.textContent.trim(),
        reason: row.querySelector(".audit-log-reason")?.textContent.trim(),
      };
    })
    .filter((row) => row.action === "policy_change")
    .slice(0, 5);

  if (rows.length === 0) {
    list.textContent = "No policy changes yet";
    return;
  }

  list.innerHTML = rows.map((row) => `
    <div class="recent-policy-item">
      <span class="recent-policy-time font-mono">${escapeHtml(row.time)}</span>
      <span class="recent-policy-reason" title="${escapeHtml(row.reason)}">${escapeHtml(row.reason)}</span>
    </div>
  `).join("");
}

let isTicking = false;
function tick() {
  if (isTicking) return;
  isTicking = true;
  if (typeof observer !== "undefined") {
    observer.disconnect();
  }
  try {
    createPolicyEditor();
    enhanceGateTransparency();
    updateRecentPolicyChanges();
  } finally {
    if (typeof observer !== "undefined") {
      observer.observe(document.body, { childList: true, subtree: true });
    }
    isTicking = false;
  }
}

hardenAttackButtonCooldown();

const observer = new MutationObserver(() => {
  tick();
});
observer.observe(document.body, { childList: true, subtree: true });

tick();
