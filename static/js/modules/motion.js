/**
 * Motion Preference Module (static/js/modules/motion.js)
 * ======================================================
 * Provides reduced-motion accessibility preference support (#task-reduced-motion):
 * - Detects OS / system reduced-motion settings (prefers-reduced-motion: reduce)
 * - Supports manual user preference: "system" (default), "reduce", "allow" (standard)
 * - Persists preference across sessions via localStorage
 * - Applies early attribute on document root to prevent Flash Of Unwanted Motion (FOUM)
 * - Removes unnecessary animations and transitions while keeping progress/loading feedback visible
 * - Dispatches change notifications and live accessibility announcements
 */

export const MOTION_STORAGE_KEY = "placement_motion_pref";

// Early motion resolution to prevent Flash Of Unwanted Motion (FOUM)
try {
  (function () {
    const stored = localStorage.getItem(MOTION_STORAGE_KEY) || "system";
    const systemReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const isReduced = stored === "reduce" || (stored === "system" && systemReduced);
    if (typeof document !== "undefined" && document.documentElement) {
      document.documentElement.setAttribute("data-motion-pref", stored);
      document.documentElement.setAttribute("data-reduced-motion", isReduced ? "true" : "false");
      if (isReduced) {
        document.documentElement.classList.add("reduced-motion");
      } else {
        document.documentElement.classList.remove("reduced-motion");
      }
    }
  })();
} catch (e) {
  // Graceful fallback for restricted storage environments
}

/**
 * Checks if the operating system / browser currently prefers reduced motion.
 * @returns {boolean}
 */
export function getSystemReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) {
    return false;
  }
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (err) {
    return false;
  }
}

/**
 * Retrieves the stored manual motion preference ('system', 'reduce', or 'allow').
 * Defaults to 'system'.
 * @returns {'system' | 'reduce' | 'allow'}
 */
export function getMotionPreference() {
  try {
    const val = localStorage.getItem(MOTION_STORAGE_KEY);
    if (val === "reduce" || val === "allow" || val === "system") {
      return val;
    }
  } catch (err) {
    // LocalStorage access may be restricted
  }
  return "system";
}

/**
 * Evaluates whether reduced motion should be active right now.
 * True if manual preference is 'reduce', or if manual preference is 'system' and OS prefers reduced motion.
 * False if manual preference is 'allow', or if 'system' and OS has standard motion.
 * @returns {boolean}
 */
export function isReducedMotion() {
  const pref = getMotionPreference();
  if (pref === "reduce") return true;
  if (pref === "allow") return false;
  return getSystemReducedMotion();
}

/**
 * Sets the manual motion preference and applies it across the document immediately.
 * @param {'system' | 'reduce' | 'allow'} preference
 * @param {boolean} [announce=true] - Whether to announce the change to screen readers
 */
export function setMotionPreference(preference, announce = true) {
  const validPref = preference === "reduce" || preference === "allow" ? preference : "system";
  try {
    localStorage.setItem(MOTION_STORAGE_KEY, validPref);
  } catch (err) {
    console.debug("Could not save motion preference to localStorage:", err);
  }

  const reduced = isReducedMotion();
  applyMotionToDOM(validPref, reduced);
  updateMotionUI(validPref, reduced);
  configureChartMotion(reduced);

  // Dispatch custom event for external listeners
  if (typeof window !== "undefined") {
    try {
      const event = new CustomEvent("motionPreferenceChanged", {
        detail: { preference: validPref, isReduced: reduced }
      });
      window.dispatchEvent(event);
    } catch (_) {}
  }

  if (announce) {
    announceMotionChange(validPref, reduced);
  }
}

/**
 * Applies motion attributes and classes to document root and body.
 * @param {string} preference
 * @param {boolean} isReduced
 */
function applyMotionToDOM(preference, isReduced) {
  if (typeof document === "undefined" || !document.documentElement) return;

  document.documentElement.setAttribute("data-motion-pref", preference);
  document.documentElement.setAttribute("data-reduced-motion", isReduced ? "true" : "false");

  if (isReduced) {
    document.documentElement.classList.add("reduced-motion");
    if (document.body) document.body.classList.add("reduced-motion");
  } else {
    document.documentElement.classList.remove("reduced-motion");
    if (document.body) document.body.classList.remove("reduced-motion");
  }
}

/**
 * Configures Chart.js global defaults so charts render without motion when preferred.
 * @param {boolean} isReduced
 */
export function configureChartMotion(isReduced) {
  if (typeof window !== "undefined" && window.Chart && window.Chart.defaults) {
    try {
      if (isReduced) {
        window.Chart.defaults.animation = false;
      } else {
        window.Chart.defaults.animation = true;
      }
    } catch (_) {}
  }
}

/**
 * Updates all motion preference selectors and indicators across the DOM.
 * @param {string} preference
 * @param {boolean} isReduced
 */
export function updateMotionUI(preference, isReduced) {
  if (typeof document === "undefined") return;

  // 1. Update dropdown menu items (.motion-pref-item)
  const menuItems = document.querySelectorAll(".motion-pref-item");
  menuItems.forEach((item) => {
    const val = item.getAttribute("data-motion-value");
    if (val === preference) {
      item.classList.add("active");
      item.setAttribute("aria-checked", "true");
    } else {
      item.classList.remove("active");
      item.setAttribute("aria-checked", "false");
    }
  });

  // 2. Update checkmark indicators in dropdowns
  const checkmarks = document.querySelectorAll(".motion-check");
  checkmarks.forEach((chk) => {
    const forVal = chk.getAttribute("data-for");
    if (forVal === preference) {
      chk.classList.remove("d-none");
    } else {
      chk.classList.add("d-none");
    }
  });

  // 3. Update radio inputs
  const radioInputs = document.querySelectorAll('input[name="motionPreference"]');
  radioInputs.forEach((radio) => {
    radio.checked = radio.value === preference;
  });

  // 4. Update select dropdowns
  const selectDropdowns = document.querySelectorAll(".motion-pref-select");
  selectDropdowns.forEach((select) => {
    select.value = preference;
  });

  // 5. Update navbar motion toggle button labels/icons
  const navIcon = document.getElementById("motionNavIcon");
  const navLabel = document.getElementById("motionNavLabel");
  if (navIcon) {
    if (isReduced) {
      navIcon.className = "fa-solid fa-person-walking text-warning me-1";
    } else {
      navIcon.className = "fa-solid fa-person-running text-primary me-1";
    }
  }
  if (navLabel) {
    if (preference === "reduce") {
      navLabel.textContent = "Motion: Off";
    } else if (preference === "allow") {
      navLabel.textContent = "Motion: On";
    } else {
      navLabel.textContent = isReduced ? "Motion: Auto (Off)" : "Motion: Auto (On)";
    }
  }

  // 6. Update status badges in settings/profile cards
  const statusBadge = document.getElementById("motionStatusBadge");
  const statusSummary = document.getElementById("motionStatusSummary");
  if (statusBadge) {
    if (isReduced) {
      statusBadge.className = "badge bg-warning-subtle text-warning border border-warning-subtle px-3 py-1 rounded-pill fw-semibold";
      statusBadge.innerHTML = '<i class="fa-solid fa-person-walking me-1"></i> Reduced Motion Active';
    } else {
      statusBadge.className = "badge bg-success-subtle text-success border border-success-subtle px-3 py-1 rounded-pill fw-semibold";
      statusBadge.innerHTML = '<i class="fa-solid fa-person-running me-1"></i> Standard Motion Active';
    }
  }
  if (statusSummary) {
    if (preference === "system") {
      statusSummary.textContent = isReduced
        ? "Following system settings (Reduced motion detected in your OS/browser)."
        : "Following system settings (Standard animations active in your OS/browser).";
    } else if (preference === "reduce") {
      statusSummary.textContent = "Manually forced: Animations, transitions, and hover motion are disabled.";
    } else {
      statusSummary.textContent = "Manually forced: Full visual animations and transitions are enabled.";
    }
  }
}

/**
 * Announces preference change to screen readers via a live region.
 * @param {string} preference
 * @param {boolean} isReduced
 */
function announceMotionChange(preference, isReduced) {
  if (typeof document === "undefined") return;

  let announcer = document.getElementById("motionLiveAnnouncer");
  if (!announcer) {
    announcer = document.createElement("div");
    announcer.id = "motionLiveAnnouncer";
    announcer.setAttribute("aria-live", "polite");
    announcer.setAttribute("aria-atomic", "true");
    announcer.className = "visually-hidden";
    document.body.appendChild(announcer);
  }

  let msg = "";
  if (preference === "reduce") {
    msg = "Motion preference set to Reduced motion. Visual animations and transitions are disabled.";
  } else if (preference === "allow") {
    msg = "Motion preference set to Standard motion. Visual animations and transitions are enabled.";
  } else {
    msg = isReduced
      ? "Motion preference set to System default. Reduced motion is currently detected."
      : "Motion preference set to System default. Standard motion is currently active.";
  }
  announcer.textContent = msg;
}

/**
 * Initializes motion preference listeners on buttons, selects, and system media queries.
 */
export function initMotionPreference() {
  const currentPref = getMotionPreference();
  const isReduced = isReducedMotion();

  applyMotionToDOM(currentPref, isReduced);
  updateMotionUI(currentPref, isReduced);
  configureChartMotion(isReduced);

  // 1. Dropdown items click listeners (.motion-pref-item)
  const menuItems = document.querySelectorAll(".motion-pref-item");
  menuItems.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const val = btn.getAttribute("data-motion-value");
      if (val) {
        setMotionPreference(val, true);
      }
    });
  });

  // 2. Select dropdown change listeners (.motion-pref-select)
  const selectDropdowns = document.querySelectorAll(".motion-pref-select");
  selectDropdowns.forEach((select) => {
    select.addEventListener("change", (e) => {
      setMotionPreference(e.target.value, true);
    });
  });

  // 3. Radio button inputs change listeners (input[name="motionPreference"])
  const radioInputs = document.querySelectorAll('input[name="motionPreference"]');
  radioInputs.forEach((radio) => {
    radio.addEventListener("change", (e) => {
      if (e.target.checked) {
        setMotionPreference(e.target.value, true);
      }
    });
  });

  // 4. Quick toggle button listener (.motion-toggle-btn without dropdown)
  const quickToggleBtns = document.querySelectorAll(".motion-toggle-quick-btn");
  quickToggleBtns.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const activePref = getMotionPreference();
      // Cycle: system -> reduce -> allow -> system
      const nextPref = activePref === "system" ? "reduce" : activePref === "reduce" ? "allow" : "system";
      setMotionPreference(nextPref, true);
    });
  });

  // 5. System media query change listener
  if (typeof window !== "undefined" && window.matchMedia) {
    try {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      const handleSystemMotionChange = () => {
        if (getMotionPreference() === "system") {
          const sysReduced = mq.matches;
          applyMotionToDOM("system", sysReduced);
          updateMotionUI("system", sysReduced);
          configureChartMotion(sysReduced);
          announceMotionChange("system", sysReduced);
        }
      };

      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", handleSystemMotionChange);
      } else if (typeof mq.addListener === "function") {
        mq.addListener(handleSystemMotionChange);
      }
    } catch (mqErr) {
      console.debug("matchMedia listener for reduced motion not supported:", mqErr);
    }
  }
}

// Expose on window for backwards compatibility and inline template handlers
if (typeof window !== "undefined") {
  window.getMotionPreference = getMotionPreference;
  window.setMotionPreference = setMotionPreference;
  window.isReducedMotion = isReducedMotion;
  window.getSystemReducedMotion = getSystemReducedMotion;
}
