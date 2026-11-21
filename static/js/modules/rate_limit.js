/**
 * Rate Limiting and Quota Feedback Module (static/js/modules/rate_limit.js)
 * =========================================================================
 * Provides live countdown timers, remaining usage indicators, accessibility
 * announcements (aria-live), and automatic button re-enabling upon cooldown expiry (#652).
 */

const activeTimers = new Map();

/**
 * Formats a duration in seconds into a friendly human-readable countdown string (e.g. "2:35", "0:09").
 * @param {number} totalSeconds
 * @returns {string} Formatted string "M:SS" or "H:MM:SS"
 */
export function formatCountdown(totalSeconds) {
  const secs = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(secs / 3600);
  const minutes = Math.floor((secs % 3600) / 60);
  const seconds = secs % 60;

  const paddedSeconds = String(seconds).padStart(2, "0");
  if (hours > 0) {
    const paddedMinutes = String(minutes).padStart(2, "0");
    return `${hours}:${paddedMinutes}:${paddedSeconds}`;
  }
  return `${minutes}:${paddedSeconds}`;
}

/**
 * Updates an indicator element displaying remaining requests for a given scope.
 * @param {string} scope - Rate limit scope (e.g. 'analyze', 'interview_eval')
 * @param {number} remaining - Number of requests remaining
 * @param {number} [limit] - Optional total limit for the scope
 */
export function updateRateLimitIndicator(scope, remaining, limit) {
  const numRemaining = Math.max(0, parseInt(remaining, 10) || 0);
  const indicators = document.querySelectorAll(`[data-scope="${scope}"]`);
  indicators.forEach((el) => {
    el.setAttribute("data-remaining", String(numRemaining));
    if (limit !== undefined) {
      el.setAttribute("data-limit", String(limit));
    }
    const countSpan = el.querySelector(".rate-limit-remaining");
    if (countSpan) {
      countSpan.textContent = String(numRemaining);
      if (numRemaining === 0) {
        countSpan.classList.add("text-danger");
        countSpan.classList.remove("text-success", "text-warning", "text-dark");
      } else if (numRemaining === 1) {
        countSpan.classList.add("text-warning");
        countSpan.classList.remove("text-danger", "text-success", "text-dark");
      } else {
        countSpan.classList.remove("text-danger", "text-warning");
        countSpan.classList.add("text-dark");
      }
    }
  });
}

/**
 * Inspects HTTP response headers (X-RateLimit-Remaining and X-RateLimit-Limit)
 * and updates matching indicators in the DOM.
 * @param {Response} response
 * @param {string} scope
 */
export function syncRateLimitFromHeaders(response, scope) {
  if (!response || !response.headers) return;
  try {
    const remainingHeader = response.headers.get("X-RateLimit-Remaining");
    const limitHeader = response.headers.get("X-RateLimit-Limit");
    if (remainingHeader !== null) {
      const remaining = parseInt(remainingHeader, 10);
      const limit = limitHeader !== null ? parseInt(limitHeader, 10) : undefined;
      if (!isNaN(remaining)) {
        updateRateLimitIndicator(scope, remaining, limit);
      }
    }
  } catch (err) {
    console.debug("Could not parse rate limit headers:", err);
  }
}

/**
 * Starts a live countdown when rate limit is exceeded.
 * Disables the submit button, updates countdown text every second,
 * and re-enables the button at zero.
 *
 * @param {Object} options
 * @param {number} options.retryAfterSeconds - Cooldown duration in seconds
 * @param {HTMLElement|string} [options.countdownElement] - Element displaying countdown string
 * @param {HTMLElement|string} [options.submitButton] - Button to disable / enable
 * @param {HTMLElement|string} [options.noticeContainer] - Container / alert element
 * @param {HTMLElement|string} [options.messageElement] - Optional status message element
 * @param {string} [options.scope] - Rate limit scope identifier
 * @param {Function} [options.onComplete] - Callback fired when countdown reaches 0
 */
export function startRateLimitCountdown({
  retryAfterSeconds,
  countdownElement,
  submitButton,
  noticeContainer,
  messageElement,
  scope = "default",
  onComplete,
}) {
  const cdEl = typeof countdownElement === "string" ? document.querySelector(countdownElement) : countdownElement;
  const btnEl = typeof submitButton === "string" ? document.querySelector(submitButton) : submitButton;
  const noticeEl = typeof noticeContainer === "string" ? document.querySelector(noticeContainer) : noticeContainer;
  const msgEl = typeof messageElement === "string" ? document.querySelector(messageElement) : messageElement;

  // Clear any existing timer for this scope
  if (activeTimers.has(scope)) {
    clearInterval(activeTimers.get(scope));
    activeTimers.delete(scope);
  }

  let remaining = Math.max(1, Math.round(Number(retryAfterSeconds) || 60));

  // Disable button
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.setAttribute("aria-disabled", "true");
    btnEl.dataset.rateLimited = "true";
  }

  // Show notice container with accessible polite aria-live announcement
  if (noticeEl) {
    noticeEl.classList.remove("d-none");
    noticeEl.setAttribute("aria-live", "polite");
  }

  // Update timer display
  function renderTick() {
    const formatted = formatCountdown(remaining);
    if (cdEl) {
      cdEl.textContent = formatted;
    }
    if (msgEl) {
      msgEl.textContent = "Rate limit reached.";
    }
  }

  renderTick();

  const intervalId = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(intervalId);
      activeTimers.delete(scope);

      // Re-enable button
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.removeAttribute("aria-disabled");
        delete btnEl.dataset.rateLimited;
      }

      // Hide notice
      if (noticeEl) {
        noticeEl.classList.add("d-none");
      }

      // Refresh rate limit status from server
      fetch(`/api/rate-limit/status?scope=${encodeURIComponent(scope)}`)
        .then((res) => res.json())
        .then((data) => {
          if (data && data.success) {
            updateRateLimitIndicator(scope, data.remaining, data.limit);
          }
        })
        .catch(() => {
          // If fetch fails, at least reset indicator to at least 1
          updateRateLimitIndicator(scope, 1);
        });

      if (typeof onComplete === "function") {
        onComplete();
      }
    } else {
      renderTick();
    }
  }, 1000);

  activeTimers.set(scope, intervalId);
  return intervalId;
}

/**
 * Handles 429 response data from an API call by triggering the countdown and updating indicators.
 */
export function handleRateLimitResponse(response, data, elements = {}) {
  const retryAfter =
    (data && (data.retry_after ?? data.retry_after_seconds)) ||
    (response && response.headers && parseInt(response.headers.get("Retry-After"), 10)) ||
    60;

  const scope = elements.scope || "analyze";
  updateRateLimitIndicator(scope, 0);

  startRateLimitCountdown({
    retryAfterSeconds: retryAfter,
    countdownElement: elements.countdownElement,
    submitButton: elements.submitButton,
    noticeContainer: elements.noticeContainer,
    messageElement: elements.messageElement,
    scope: scope,
    onComplete: elements.onComplete,
  });
}

/**
 * Automatically initializes rate limit indicators on the page.
 * If any indicator shows 0 remaining and has a positive reset-seconds, starts the countdown immediately.
 */
export function initRateLimitIndicators() {
  const indicators = document.querySelectorAll("[data-scope]");
  indicators.forEach((indicator) => {
    const scope = indicator.getAttribute("data-scope");
    const remaining = parseInt(indicator.getAttribute("data-remaining") || "0", 10);
    const resetSeconds = parseInt(indicator.getAttribute("data-reset-seconds") || "0", 10);

    if (remaining === 0 && resetSeconds > 0) {
      if (scope === "analyze") {
        startRateLimitCountdown({
          retryAfterSeconds: resetSeconds,
          countdownElement: document.getElementById("analyzeCountdownTimer"),
          submitButton: document.getElementById("btnSubmitAnalysis"),
          noticeContainer: document.getElementById("analyzeRateLimitNotice"),
          messageElement: document.getElementById("analyzeRateLimitMessage"),
          scope: "analyze",
        });
      } else if (scope === "interview_eval") {
        startRateLimitCountdown({
          retryAfterSeconds: resetSeconds,
          countdownElement: document.getElementById("interviewCountdownTimer"),
          submitButton: document.getElementById("btnSubmitAnswer") || document.querySelector("#chatForm button[type='submit']"),
          noticeContainer: document.getElementById("interviewRateLimitNotice"),
          messageElement: document.getElementById("interviewRateLimitMessage"),
          scope: "interview_eval",
        });
      }
    }
  });
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initRateLimitIndicators);
  } else {
    initRateLimitIndicators();
  }
}
