/**
 * Drive Day Practical Readiness Checklist Module (static/js/modules/drive_checklist.js)
 * ====================================================================================
 * Client-side behaviors for toggling tasks, adding custom items, renaming, deleting,
 * switching drive presets (offline vs. online), and application binding (#651).
 */

import { getCsrfToken, escapeHtml, showToast } from "./utils.js";

/**
 * Updates progress indicators in the DOM from server progress payload.
 */
function updateProgressUI(data) {
  if (!data) return;

  // Overall progress bar and percentage
  const progressBar = document.getElementById("overallProgressBar");
  const percentageText = document.getElementById("progressPercentageText");
  const readyText = document.getElementById("progressReadyText");

  if (progressBar) {
    progressBar.style.width = `${data.completion_percentage}%`;
    progressBar.setAttribute("aria-valuenow", data.completion_percentage);
  }
  if (percentageText) {
    percentageText.textContent = `${data.completion_percentage}%`;
  }
  if (readyText) {
    readyText.textContent = data.progress_label || `${data.completed_items} of ${data.total_items} ready`;
  }

  // Category breakdown badges and quick pills
  if (data.category_stats) {
    Object.entries(data.category_stats).forEach(([catKey, catStat]) => {
      const badge = document.getElementById(`badgeCat_${catKey}`);
      if (badge) {
        badge.textContent = catStat.ready_label;
      }
      const pill = document.querySelector(`.category-pill-count[data-cat="${catKey}"]`);
      if (pill) {
        pill.textContent = catStat.ready_label;
      }
    });
  }
}

/**
 * Retrieves the currently active application_id and drive mode from DOM.
 */
function getActiveContext() {
  const container = document.getElementById("checklistCategoriesContainer");
  const appId = container ? container.getAttribute("data-application-id") || "" : "";
  const mode = container ? container.getAttribute("data-mode") || "offline" : "offline";
  return { appId, mode };
}

/**
 * Attaches event listeners for item checkboxes (toggle completed).
 */
export function initCheckboxToggles() {
  document.addEventListener("change", async (e) => {
    if (!e.target.classList.contains("item-checkbox")) return;

    const checkbox = e.target;
    const row = checkbox.closest(".checklist-item-row");
    if (!row) return;

    const itemId = row.getAttribute("data-item-id");
    const isCompleted = checkbox.checked;
    const { appId } = getActiveContext();

    // Optimistic UI update
    if (isCompleted) {
      row.classList.add("is-completed", "bg-body-tertiary");
    } else {
      row.classList.remove("is-completed", "bg-body-tertiary");
    }

    try {
      const res = await fetch("/api/drive-day-checklist/toggle", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          application_id: appId,
          item_id: itemId,
          completed: isCompleted,
        }),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || "Failed to update task state.");
      }

      updateProgressUI(json.data);
    } catch (err) {
      console.error("Task toggle failed:", err);
      // Revert optimistic update
      checkbox.checked = !isCompleted;
      if (checkbox.checked) {
        row.classList.add("is-completed", "bg-body-tertiary");
      } else {
        row.classList.remove("is-completed", "bg-body-tertiary");
      }
      alert(err.message || "Failed to update item status. Please try again.");
    }
  });
}

/**
 * Creates DOM markup for a new checklist item row.
 */
function createItemRowElement(item, category) {
  const row = document.createElement("div");
  row.className = `checklist-item-row p-2 px-3 mb-2 border d-flex align-items-center justify-content-between gap-2 ${item.completed ? "is-completed bg-body-tertiary" : ""}`;
  row.id = `itemRow_${item.id}`;
  row.setAttribute("data-item-id", item.id);
  row.setAttribute("data-category", category);

  row.innerHTML = `
    <div class="form-check d-flex align-items-center gap-2 m-0 flex-grow-1">
      <input class="form-check-input item-checkbox fs-5 m-0"
             type="checkbox"
             id="check_${escapeHtml(item.id)}"
             ${item.completed ? "checked" : ""}
             aria-label="${escapeHtml(item.text)}">
      
      <span class="item-text ms-1 fw-normal" id="itemTextSpan_${escapeHtml(item.id)}">
        ${escapeHtml(item.text)}
      </span>
    </div>

    <div class="d-flex align-items-center gap-1 item-actions">
      <button type="button" class="btn btn-sm btn-link text-secondary p-1 btn-rename-item"
              data-item-id="${escapeHtml(item.id)}"
              title="Rename task description"
              aria-label="Rename task ${escapeHtml(item.text)}">
        <i class="fa-solid fa-pen-to-square"></i>
      </button>
      <button type="button" class="btn btn-sm btn-link text-danger p-1 btn-delete-item"
              data-item-id="${escapeHtml(item.id)}"
              title="Delete task item"
              aria-label="Delete task ${escapeHtml(item.text)}">
        <i class="fa-regular fa-trash-can"></i>
      </button>
    </div>
  `;
  return row;
}

/**
 * Initializes Add Item accordion and submission logic.
 */
export function initAddItemHandlers() {
  // Show Add form
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".btn-show-add-form");
    if (!trigger) return;

    const cat = trigger.getAttribute("data-category");
    const container = document.getElementById(`addFormContainer_${cat}`);
    if (container) {
      container.classList.remove("d-none");
      trigger.classList.add("d-none");
      const input = container.querySelector(".add-item-input");
      if (input) input.focus();
    }
  });

  // Cancel Add form
  document.addEventListener("click", (e) => {
    const cancelBtn = e.target.closest(".btn-cancel-add");
    if (!cancelBtn) return;

    const cat = cancelBtn.getAttribute("data-category");
    const container = document.getElementById(`addFormContainer_${cat}`);
    const trigger = document.querySelector(`.btn-show-add-form[data-category="${cat}"]`);
    if (container) container.classList.add("d-none");
    if (trigger) trigger.classList.remove("d-none");
  });

  // Submit Add form
  async function submitNewItem(cat) {
    const container = document.getElementById(`addFormContainer_${cat}`);
    if (!container) return;

    const input = container.querySelector(".add-item-input");
    const text = input ? input.value.trim() : "";
    if (!text) return;

    const { appId } = getActiveContext();

    try {
      const res = await fetch("/api/drive-day-checklist/item", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          application_id: appId,
          category: cat,
          text: text,
        }),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || "Failed to add item.");
      }

      // Append new row to items list
      const itemsList = document.getElementById(`itemsList_${cat}`);
      const catItems = json.data.checklist[cat] || [];
      const createdItem = catItems[catItems.length - 1];

      if (itemsList && createdItem) {
        const rowEl = createItemRowElement(createdItem, cat);
        itemsList.appendChild(rowEl);
      }

      // Reset form
      if (input) input.value = "";
      container.classList.add("d-none");
      const trigger = document.querySelector(`.btn-show-add-form[data-category="${cat}"]`);
      if (trigger) trigger.classList.remove("d-none");

      updateProgressUI(json.data);
    } catch (err) {
      console.error("Add item failed:", err);
      alert(err.message || "Failed to add checklist item.");
    }
  }

  document.addEventListener("click", (e) => {
    const submitBtn = e.target.closest(".btn-submit-add-item");
    if (!submitBtn) return;
    const cat = submitBtn.getAttribute("data-category");
    submitNewItem(cat);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.classList.contains("add-item-input")) {
      e.preventDefault();
      const container = e.target.closest(".add-item-form-container");
      if (container) {
        const cat = container.id.replace("addFormContainer_", "");
        submitNewItem(cat);
      }
    }
  });
}

/**
 * Initializes Rename Item handlers.
 */
export function initRenameHandlers() {
  document.addEventListener("click", async (e) => {
    const renameBtn = e.target.closest(".btn-rename-item");
    if (!renameBtn) return;

    const itemId = renameBtn.getAttribute("data-item-id");
    const textSpan = document.getElementById(`itemTextSpan_${itemId}`);
    if (!textSpan) return;

    const currentText = textSpan.textContent.trim();
    const newText = prompt("Edit checklist item description:", currentText);
    if (newText === null || newText.trim() === "" || newText.trim() === currentText) return;

    const { appId } = getActiveContext();

    try {
      const res = await fetch("/api/drive-day-checklist/item", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          application_id: appId,
          item_id: itemId,
          text: newText.trim(),
        }),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || "Failed to rename item.");
      }

      textSpan.textContent = newText.trim();
      updateProgressUI(json.data);
    } catch (err) {
      console.error("Rename item failed:", err);
      alert(err.message || "Could not rename task.");
    }
  });
}

/**
 * Initializes Delete Item handlers.
 */
export function initDeleteHandlers() {
  document.addEventListener("click", async (e) => {
    const deleteBtn = e.target.closest(".btn-delete-item");
    if (!deleteBtn) return;

    const itemId = deleteBtn.getAttribute("data-item-id");
    const row = document.getElementById(`itemRow_${itemId}`);
    if (!confirm("Are you sure you want to delete this checklist item?")) return;

    const { appId } = getActiveContext();

    try {
      const res = await fetch("/api/drive-day-checklist/item", {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          application_id: appId,
          item_id: itemId,
        }),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || "Failed to delete item.");
      }

      if (row) row.remove();
      updateProgressUI(json.data);
    } catch (err) {
      console.error("Delete item failed:", err);
      alert(err.message || "Could not delete task.");
    }
  });
}

/**
 * Initializes Application Binding selector change.
 */
export function initApplicationSelector() {
  const selectApp = document.getElementById("selectApplication");
  if (!selectApp) return;

  selectApp.addEventListener("change", () => {
    const targetAppId = selectApp.value;
    const { mode } = getActiveContext();
    const query = new URLSearchParams();
    if (targetAppId) query.set("application_id", targetAppId);
    if (mode) query.set("mode", mode);
    window.location.href = `/drive-day-checklist?${query.toString()}`;
  });
}

/**
 * Initializes Drive Mode (Offline / Online) Switcher.
 */
export function initModeSwitcher() {
  const modeButtons = document.querySelectorAll(".mode-switcher-btn");
  modeButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const targetMode = btn.getAttribute("data-mode");
      const { appId, mode } = getActiveContext();
      if (targetMode === mode) return;

      const query = new URLSearchParams();
      if (appId) query.set("application_id", appId);
      query.set("mode", targetMode);
      window.location.href = `/drive-day-checklist?${query.toString()}`;
    });
  });
}

/**
 * Initializes Reset to Defaults button.
 */
export function initResetChecklist() {
  const resetBtn = document.getElementById("btnResetChecklist");
  if (!resetBtn) return;

  resetBtn.addEventListener("click", async () => {
    if (!confirm("Reset all items in this checklist to the default template? Any custom items will be replaced.")) {
      return;
    }

    const { appId, mode } = getActiveContext();

    try {
      const res = await fetch("/api/drive-day-checklist/reset", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          application_id: appId,
          mode: mode,
        }),
      });

      const json = await res.json();
      if (!res.ok || !json.success) {
        throw new Error(json.error || "Failed to reset checklist.");
      }

      // Reload page to reflect fresh defaults
      window.location.reload();
    } catch (err) {
      console.error("Reset checklist failed:", err);
      alert(err.message || "Could not reset checklist.");
    }
  });
}

// Auto-initialize when loaded
if (typeof document !== "undefined") {
  const initAll = () => {
    initCheckboxToggles();
    initAddItemHandlers();
    initRenameHandlers();
    initDeleteHandlers();
    initApplicationSelector();
    initModeSwitcher();
    initResetChecklist();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
}
