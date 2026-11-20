/**
 * Shared Utilities Module (static/js/modules/utils.js)
 * ====================================================
 * Common frontend helper functions:
 * - CSRF token retrieval & fetch request interceptor (#300)
 * - Safe HTML entity escaping
 * - Floating toast notifications (accessible aria-live region)
 * - Clipboard copy helper with fallback for non-secure contexts
 * - String and text counting helpers
 */

/**
 * Retrieves CSRF token from page meta tag or hidden input field.
 * @returns {string}
 */
export function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.getAttribute("content")) {
    return meta.getAttribute("content");
  }
  const input = document.querySelector('input[name="csrf_token"]');
  if (input && input.value) {
    return input.value;
  }
  return "";
}

/**
 * Escapes unsafe HTML characters to prevent XSS.
 * @param {string|any} str
 * @returns {string}
 */
export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  if (typeof str !== "string") str = String(str);
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Initializes automatic CSRF header injection for window.fetch.
 */
export function initCsrfFetch() {
  if (typeof window === "undefined" || typeof window.fetch !== "function") return;
  if (window.__csrfFetchInitialized) return;
  window.__csrfFetchInitialized = true;

  const originalFetch = window.fetch;
  window.fetch = function (resource, init) {
    init = init || {};
    const method = (init.method || "GET").toUpperCase();
    if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
      const token = getCsrfToken();
      if (token) {
        if (!init.headers) {
          init.headers = {};
        }
        if (init.headers instanceof Headers) {
          if (!init.headers.has("X-CSRFToken")) {
            init.headers.append("X-CSRFToken", token);
          }
          if (!init.headers.has("X-CSRF-Token")) {
            init.headers.append("X-CSRF-Token", token);
          }
        } else if (Array.isArray(init.headers)) {
          const hasCsrf = init.headers.some(
            ([k]) => k.toLowerCase() === "x-csrftoken" || k.toLowerCase() === "x-csrf-token"
          );
          if (!hasCsrf) {
            init.headers.push(["X-CSRFToken", token]);
            init.headers.push(["X-CSRF-Token", token]);
          }
        } else {
          if (!init.headers["X-CSRFToken"] && !init.headers["x-csrftoken"]) {
            init.headers["X-CSRFToken"] = token;
          }
          if (!init.headers["X-CSRF-Token"] && !init.headers["x-csrf-token"]) {
            init.headers["X-CSRF-Token"] = token;
          }
        }
      }
    }
    return originalFetch.call(this, resource, init);
  };
}

// Auto-initialize CSRF interceptor on module load
initCsrfFetch();

/**
 * Custom fetch wrapper that ensures CSRF headers and JSON defaults.
 * @param {string} url
 * @param {RequestInit} options
 * @returns {Promise<Response>}
 */
export async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});

  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    const token = getCsrfToken();
    if (token) {
      if (!headers.has("X-CSRFToken")) headers.set("X-CSRFToken", token);
      if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", token);
    }
    if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
  }

  return fetch(url, { ...options, headers });
}

/**
 * Gets or creates the global toast container.
 * @returns {HTMLElement}
 */
export function getOrCreateToastContainer() {
  let container = document.getElementById("globalToastContainer");
  if (!container) {
    container = document.getElementById("copyToastContainer");
  }
  if (!container) {
    container = document.createElement("div");
    container.id = "globalToastContainer";
    container.className = "copy-toast-container";
    container.setAttribute("aria-live", "polite");
    container.setAttribute("aria-atomic", "true");
    document.body.appendChild(container);
  }
  return container;
}

/**
 * Displays a non-intrusive floating toast notification.
 * @param {string} message
 * @param {boolean|string} typeOrIsSuccess
 */
export function showToast(message, typeOrIsSuccess = "info") {
  const container = getOrCreateToastContainer();
  const toast = document.createElement("div");
  toast.className = "copy-toast";
  toast.setAttribute("role", "status");

  let iconClass = "fa-solid fa-circle-info text-primary";
  if (typeOrIsSuccess === true || typeOrIsSuccess === "success") {
    iconClass = "fa-solid fa-circle-check text-success";
  } else if (typeOrIsSuccess === false || typeOrIsSuccess === "error" || typeOrIsSuccess === "danger") {
    iconClass = "fa-solid fa-circle-exclamation text-danger";
  } else if (typeOrIsSuccess === "warning") {
    iconClass = "fa-solid fa-triangle-exclamation text-warning";
  }

  toast.innerHTML = `
    <i class="${iconClass} flex-shrink-0"></i>
    <span class="flex-grow-1">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      toast.classList.add("show");
    });
  });

  setTimeout(() => {
    toast.classList.remove("show");
    toast.classList.add("fade-out");
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }, 2600);
}

// Make showToast accessible globally for inline script hooks
if (typeof window !== "undefined") {
  window.showToast = showToast;
  window.escapeHtml = escapeHtml;
  window.getCsrfToken = getCsrfToken;
}

/**
 * Modern clipboard helper with fallback for insecure or older contexts.
 * @param {string} text
 * @returns {Promise<boolean>}
 */
export async function copyToClipboard(text) {
  if (!text || typeof text !== "string") return false;
  const clean = text.trim();
  if (!clean) return false;

  if (navigator.clipboard && window.isSecureContext && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(clean);
      return true;
    } catch (err) {
      console.warn("navigator.clipboard.writeText failed, falling back:", err);
    }
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = clean;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const successful = document.execCommand("copy");
    document.body.removeChild(textarea);
    return successful;
  } catch (err) {
    console.error("document.execCommand fallback copy failed:", err);
    return false;
  }
}

/**
 * Word and paragraph counter helpers.
 */
export function countParas(text) {
  if (!text || !text.trim()) return 0;
  return text.trim().split(/\n\s*\n+/).filter((p) => p.trim().length > 0).length;
}

export function countWords(text) {
  if (!text || !text.trim()) return 0;
  return (text.trim().match(/\S+/g) || []).length;
}

// Expose on window for backwards compatibility with inline scripts and legacy consumers
if (typeof window !== "undefined") {
  window.getCsrfToken = getCsrfToken;
  window.escapeHtml = escapeHtml;
  window.showToast = showToast;
  window.copyToClipboard = copyToClipboard;
}

