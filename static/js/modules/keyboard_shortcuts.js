/**
 * Keyboard Shortcuts Module (static/js/modules/keyboard_shortcuts.js)
 * =================================================================
 * Provides lightweight global keyboard navigation and an accessible help dialog (#691):
 * - Sequence shortcuts:
 *   - 'g' then 'd' -> Go to Dashboard (/)
 *   - 'g' then 'i' -> Go to Mock Interview Practice (/interview)
 *   - 'g' then 't' -> Go to Applications Tracker (/applications)
 *   - 'g' then 'c' -> Go to Coding Practice (/coding-practice)
 * - Single-key shortcuts:
 *   - '/'          -> Focus search input (or navigate to /search)
 *   - '?'          -> Open accessible keyboard shortcuts help dialog
 *   - 'Escape'     -> Close help dialog or active modal dialogs
 *
 * Accessibility & Guardrails:
 * - Ignored when user is typing inside input, textarea, select, or contenteditable.
 * - Ignored when modifier keys (Ctrl, Alt, Meta) are held down, guaranteeing
 *   zero conflicts with existing shortcuts (e.g. Ctrl+Enter to submit, Ctrl+C).
 * - Focus trapping and aria-modal on the help dialog.
 * - Restores focus to the triggering element upon dialog dismissal.
 */

export const KEYBOARD_NAVIGATION_MAP = {
  d: "/",
  i: "/interview",
  t: "/applications",
  c: "/coding-practice",
  h: "/",
  p: "/coding-practice",
  a: "/applications",
};

const NON_TYPING_INPUT_TYPES = new Set([
  "button",
  "submit",
  "reset",
  "checkbox",
  "radio",
  "file",
  "image",
  "range",
  "color",
]);

let previousActiveElement = null;
let pendingSequence = null;
let sequenceTimer = null;

/**
 * Checks whether an active element represents a user typing input field.
 */
export function isTypingElement(target) {
  if (!target) return false;
  if (
    target.isContentEditable ||
    target.getAttribute("contenteditable") === "true" ||
    target.getAttribute("contenteditable") === ""
  ) {
    return true;
  }
  const tag = (target.tagName || "").toLowerCase();
  if (tag === "textarea" || tag === "select") {
    return true;
  }
  if (tag === "input") {
    const type = (target.type || "text").toLowerCase();
    return !NON_TYPING_INPUT_TYPES.has(type);
  }
  if (
    target.closest &&
    (target.closest(".monaco-editor") ||
      target.closest(".cm-editor") ||
      target.closest(".ace_editor"))
  ) {
    return true;
  }
  return false;
}

/**
 * Locates the most appropriate search input on the current page.
 */
export function findSearchInput(root = document) {
  const selectors = [
    'input[type="search"]',
    "#search",
    "#search-input",
    "#searchQuery",
    "#companySearchInput",
    "#bookmarkSearchInput",
    "#noteSearchInput",
    "#leaderboardSearch",
    "#skillSearchInput",
    'input[name="search"]',
    'input[name="q"]',
    'input[placeholder*="search" i]',
  ];

  for (const sel of selectors) {
    const el = root.querySelector(sel);
    if (el && !el.disabled) {
      return el;
    }
  }
  return null;
}

/**
 * Ensures the shortcuts help modal DOM element exists on the page.
 */
export function ensureShortcutsModal() {
  let modal = document.getElementById("shortcutsHelpModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.className = "modal fade";
    modal.id = "shortcutsHelpModal";
    modal.tabIndex = -1;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "shortcutsHelpModalTitle");
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-lg" role="document">
        <div class="modal-content shadow-lg border-0 rounded-4 overflow-hidden">
          <div class="modal-header bg-light border-bottom px-4 py-3">
            <h5 class="modal-title fw-bold text-dark d-flex align-items-center gap-2 mb-0" id="shortcutsHelpModalTitle">
              <i class="fa-solid fa-keyboard text-primary" aria-hidden="true"></i> Keyboard Shortcuts
            </h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" id="shortcutsHelpCloseBtn" aria-label="Close keyboard shortcuts dialog"></button>
          </div>
          <div class="modal-body px-4 py-3">
            <div class="row g-4">
              <div class="col-md-6">
                <h6 class="text-uppercase text-muted fw-bold small mb-3">
                  <i class="fa-solid fa-compass me-1 text-primary" aria-hidden="true"></i> Navigation
                </h6>
                <div class="list-group list-group-flush border rounded-3 mb-3">
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Dashboard</span>
                    <span><kbd class="shortcut-kbd">g</kbd> <span class="text-muted small">then</span> <kbd class="shortcut-kbd">d</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Mock Interview Practice</span>
                    <span><kbd class="shortcut-kbd">g</kbd> <span class="text-muted small">then</span> <kbd class="shortcut-kbd">i</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Application Tracker</span>
                    <span><kbd class="shortcut-kbd">g</kbd> <span class="text-muted small">then</span> <kbd class="shortcut-kbd">t</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Coding Practice</span>
                    <span><kbd class="shortcut-kbd">g</kbd> <span class="text-muted small">then</span> <kbd class="shortcut-kbd">c</kbd></span>
                  </div>
                </div>
              </div>
              <div class="col-md-6">
                <h6 class="text-uppercase text-muted fw-bold small mb-3">
                  <i class="fa-solid fa-bolt me-1 text-warning" aria-hidden="true"></i> Actions & Dialogs
                </h6>
                <div class="list-group list-group-flush border rounded-3 mb-3">
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Focus Search</span>
                    <span><kbd class="shortcut-kbd">/</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Open Shortcuts Help</span>
                    <span><kbd class="shortcut-kbd">?</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Close Dialog / Cancel</span>
                    <span><kbd class="shortcut-kbd">Esc</kbd></span>
                  </div>
                  <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-3">
                    <span class="small">Submit Answer / Run Code</span>
                    <span><kbd class="shortcut-kbd">Ctrl</kbd> + <kbd class="shortcut-kbd">Enter</kbd></span>
                  </div>
                </div>
              </div>
            </div>
            <div class="alert alert-light border rounded-3 small text-muted mb-0 d-flex align-items-center gap-2">
              <i class="fa-solid fa-circle-info text-primary" aria-hidden="true"></i>
              <span>Shortcuts are inactive while typing inside inputs, textareas, or editable elements.</span>
            </div>
          </div>
          <div class="modal-footer bg-light border-top px-4 py-2">
            <button type="button" class="btn btn-secondary btn-sm rounded-pill px-3" data-bs-dismiss="modal" id="shortcutsHelpFooterCloseBtn">Close</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  return modal;
}

/**
 * Opens the shortcuts help dialog with accessibility attributes and focus trapping.
 */
export function openShortcutsModal() {
  const modal = ensureShortcutsModal();
  previousActiveElement = document.activeElement;

  if (window.bootstrap && window.bootstrap.Modal) {
    const bsModal = window.bootstrap.Modal.getOrCreateInstance(modal);
    bsModal.show();
  } else {
    modal.classList.add("show");
    modal.style.display = "block";
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  }

  setTimeout(() => {
    const focusable =
      modal.querySelector("#shortcutsHelpCloseBtn") ||
      modal.querySelector("button, [tabindex]:not([tabindex='-1'])");
    if (focusable && typeof focusable.focus === "function") {
      focusable.focus();
    }
  }, 50);
}

/**
 * Closes the shortcuts help dialog and returns focus to the previously active element.
 */
export function closeShortcutsModal() {
  const modal = document.getElementById("shortcutsHelpModal");
  if (!modal) return;

  if (window.bootstrap && window.bootstrap.Modal) {
    const bsModal = window.bootstrap.Modal.getInstance(modal);
    if (bsModal) {
      bsModal.hide();
    } else {
      modal.classList.remove("show");
      modal.style.display = "none";
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
    }
  } else {
    modal.classList.remove("show");
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
  }

  if (previousActiveElement && typeof previousActiveElement.focus === "function") {
    try {
      previousActiveElement.focus();
    } catch (_) {}
    previousActiveElement = null;
  }
}

/**
 * Core keydown handler for keyboard shortcuts.
 */
export function handleKeydownEvent(e, options = {}) {
  const target = e.target;

  // 1. Ignore shortcuts when typing inside form fields or editable areas
  if (isTypingElement(target)) {
    pendingSequence = null;
    return;
  }

  // 2. Ignore if modifier keys (Ctrl, Alt, Meta) are held down
  // Guarantees zero conflict with Ctrl+Enter or browser combinations
  if (e.ctrlKey || e.altKey || e.metaKey) {
    pendingSequence = null;
    return;
  }

  const key = e.key;

  // 3. Escape key closes dialogs
  if (key === "Escape" || key === "Esc") {
    const helpModal = document.getElementById("shortcutsHelpModal");
    if (
      helpModal &&
      (helpModal.classList.contains("show") || helpModal.style.display === "block")
    ) {
      e.preventDefault();
      closeShortcutsModal();
      return;
    }

    const anyModal = document.querySelector(".modal.show");
    if (anyModal) {
      e.preventDefault();
      if (window.bootstrap && window.bootstrap.Modal) {
        const inst = window.bootstrap.Modal.getInstance(anyModal);
        if (inst) inst.hide();
      } else {
        const closeBtn = anyModal.querySelector('[data-bs-dismiss="modal"]');
        if (closeBtn) closeBtn.click();
      }
      return;
    }
    pendingSequence = null;
    return;
  }

  // 4. '?' opens the help dialog
  if (key === "?") {
    e.preventDefault();
    pendingSequence = null;
    openShortcutsModal();
    return;
  }

  // 5. '/' focuses search
  if (key === "/") {
    e.preventDefault();
    pendingSequence = null;
    const searchInput = findSearchInput(document);
    if (searchInput) {
      searchInput.focus();
      if (typeof searchInput.select === "function") {
        searchInput.select();
      }
    } else {
      const navigate =
        options.navigate ||
        ((url) => {
          window.location.href = url;
        });
      navigate("/search");
    }
    return;
  }

  // 6. Navigation sequences starting with 'g'
  const lowerKey = key.toLowerCase();
  if (pendingSequence === "g") {
    clearTimeout(sequenceTimer);
    pendingSequence = null;
    if (KEYBOARD_NAVIGATION_MAP[lowerKey]) {
      e.preventDefault();
      const targetUrl = KEYBOARD_NAVIGATION_MAP[lowerKey];
      const navigate =
        options.navigate ||
        ((url) => {
          window.location.href = url;
        });
      navigate(targetUrl);
    }
    return;
  }

  if (lowerKey === "g") {
    pendingSequence = "g";
    clearTimeout(sequenceTimer);
    sequenceTimer = setTimeout(() => {
      pendingSequence = null;
    }, 1500);
    return;
  }

  pendingSequence = null;
}

/**
 * Traps Tab focus within the open shortcuts help modal.
 */
export function initModalFocusTrap() {
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const modal = document.getElementById("shortcutsHelpModal");
    if (!modal || (!modal.classList.contains("show") && modal.style.display !== "block")) {
      return;
    }
    const focusableSelector =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusables = Array.from(modal.querySelectorAll(focusableSelector)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first || !modal.contains(document.activeElement)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last || !modal.contains(document.activeElement)) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}

/**
 * Initializes the keyboard shortcuts listener and dismiss button handlers.
 */
export function initKeyboardShortcuts() {
  ensureShortcutsModal();
  initModalFocusTrap();
  document.addEventListener("keydown", handleKeydownEvent);
  document.addEventListener("click", (e) => {
    if (
      e.target &&
      e.target.closest(
        "#shortcutsHelpCloseBtn, #shortcutsHelpFooterCloseBtn, [data-dismiss-shortcuts]"
      )
    ) {
      closeShortcutsModal();
    }
    const modal = document.getElementById("shortcutsHelpModal");
    if (modal && e.target === modal) {
      closeShortcutsModal();
    }
  });
}

if (typeof window !== "undefined") {
  window.initKeyboardShortcuts = initKeyboardShortcuts;
  window.openShortcutsModal = openShortcutsModal;
  window.closeShortcutsModal = closeShortcutsModal;
}
