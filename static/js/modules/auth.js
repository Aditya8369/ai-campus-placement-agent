/**
 * Authentication Module (static/js/modules/auth.js)
 * =================================================
 * Password visibility toggle, real-time strength meter, and credential rules (#290).
 */

import { escapeHtml } from "./utils.js";

export function initPasswordStrengthIndicator() {
  const passwordInput = document.getElementById("regPassword");
  const toggleBtn = document.getElementById("togglePasswordBtn");
  const toggleIcon = document.getElementById("togglePasswordIcon");
  const container = document.getElementById("passwordStrengthContainer");
  const progressBar = document.getElementById("strengthProgressBar");
  const strengthLabel = document.getElementById("strengthLabel");
  const reqLength = document.getElementById("reqLength");
  const reqUpper = document.getElementById("reqUpper");
  const reqLower = document.getElementById("reqLower");
  const reqNumber = document.getElementById("reqNumber");
  const reqSpecial = document.getElementById("reqSpecial");
  const suggestionsBox = document.getElementById("passwordSuggestions");
  const suggestionsList = document.getElementById("suggestionsList");

  // Show / Hide Password toggle (buttons marked .toggle-password-visibility are
  // already handled by initPasswordToggle, skip them here so they do not flip twice)
  if (toggleBtn && passwordInput && !toggleBtn.classList.contains("toggle-password-visibility")) {
    toggleBtn.addEventListener("click", () => {
      const isPassword = passwordInput.getAttribute("type") === "password";
      const newType = isPassword ? "text" : "password";
      passwordInput.setAttribute("type", newType);
      toggleBtn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
      toggleBtn.setAttribute("title", isPassword ? "Hide password" : "Show password");
      if (toggleIcon) {
        if (isPassword) {
          toggleIcon.classList.remove("fa-eye");
          toggleIcon.classList.add("fa-eye-slash");
        } else {
          toggleIcon.classList.remove("fa-eye-slash");
          toggleIcon.classList.add("fa-eye");
        }
      }
    });
  }

  if (!passwordInput) return;

  function evaluateStrength(val) {
    if (!val) {
      return {
        score: 0,
        percentage: 0,
        strength: "Empty",
        criteria: { length: false, upper: false, lower: false, number: false, special: false },
        suggestions: [
          "Use at least 8 characters.",
          "Include both uppercase and lowercase letters.",
          "Include at least one number (0-9).",
          "Include at least one special character (e.g. !@#$%^&*)."
        ]
      };
    }

    const hasLength = val.length >= 8;
    const hasUpper = /[A-Z]/.test(val);
    const hasLower = /[a-z]/.test(val);
    const hasNumber = /[0-9]/.test(val);
    const hasSpecial = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?~`]/.test(val);

    let count = 0;
    if (hasLength) count++;
    if (hasUpper) count++;
    if (hasLower) count++;
    if (hasNumber) count++;
    if (hasSpecial) count++;

    let score = count;
    if (!hasLength && score > 2) {
      score = 2;
    }

    let strength = "Weak";
    if (score >= 5) {
      strength = "Strong";
    } else if (score >= 3) {
      strength = "Medium";
    }

    const suggestions = [];
    if (!hasLength) suggestions.push("Use at least 8 characters.");
    if (!hasLower) suggestions.push("Add at least one lowercase letter (a-z).");
    if (!hasUpper) suggestions.push("Add at least one uppercase letter (A-Z).");
    if (!hasNumber) suggestions.push("Add at least one number (0-9).");
    if (!hasSpecial) suggestions.push("Add at least one special character (e.g. !@#$%^&*).");

    return {
      score: score,
      percentage: score * 20,
      strength: strength,
      criteria: {
        length: hasLength,
        upper: hasUpper,
        lower: hasLower,
        number: hasNumber,
        special: hasSpecial
      },
      suggestions: suggestions
    };
  }

  function setRequirementState(el, met) {
    if (!el) return;
    const icon = el.querySelector("i");
    if (met) {
      el.className = "req-item req-met";
      if (icon) {
        icon.className = "fa-solid fa-circle-check me-1";
      }
    } else {
      el.className = "req-item req-unmet";
      if (icon) {
        icon.className = "fa-regular fa-circle me-1";
      }
    }
  }

  function updateIndicator() {
    const val = passwordInput.value;
    if (!val) {
      if (container) container.classList.add("d-none");
      return;
    }

    if (container) container.classList.remove("d-none");

    const evaluation = evaluateStrength(val);

    // Update Progress Bar
    if (progressBar) {
      progressBar.style.width = evaluation.percentage + "%";
      progressBar.setAttribute("aria-valuenow", evaluation.percentage);
      progressBar.className = "progress-bar " + (
        evaluation.strength === "Strong" ? "strength-bar-strong" :
        evaluation.strength === "Medium" ? "strength-bar-medium" : "strength-bar-weak"
      );
    }

    // Update Strength Label
    if (strengthLabel) {
      strengthLabel.textContent = evaluation.strength;
      strengthLabel.className = "badge rounded-pill " + (
        evaluation.strength === "Strong" ? "strength-badge-strong" :
        evaluation.strength === "Medium" ? "strength-badge-medium" : "strength-badge-weak"
      );
    }

    // Update Requirement List
    setRequirementState(reqLength, evaluation.criteria.length);
    setRequirementState(reqUpper, evaluation.criteria.upper);
    setRequirementState(reqLower, evaluation.criteria.lower);
    setRequirementState(reqNumber, evaluation.criteria.number);
    setRequirementState(reqSpecial, evaluation.criteria.special);

    // Update Suggestions
    if (suggestionsBox && suggestionsList) {
      if (evaluation.suggestions.length > 0 && evaluation.strength !== "Strong") {
        suggestionsList.innerHTML = evaluation.suggestions.map(s => `<li>${s}</li>`).join("");
        suggestionsBox.classList.remove("d-none");
      } else {
        suggestionsList.innerHTML = "";
        suggestionsBox.classList.add("d-none");
      }
    }
  }

  passwordInput.addEventListener("input", updateIndicator);
  passwordInput.addEventListener("keyup", updateIndicator);
  passwordInput.addEventListener("paste", () => {
    setTimeout(updateIndicator, 20);
  });
}

/**
 * Session Expiration and Automatic Inactivity Logout Handler
 * - Monitors authenticated session duration and inactivity
 * - Displays accessible warning modal with real-time countdown before expiration
 * - Allows user to continue/extend session via Keep-Alive ping
 * - Automatically logs out and redirects to login on session expiration
 */


export function initPasswordToggle() {
  const toggleButtons = document.querySelectorAll(".toggle-password-visibility");
  toggleButtons.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const targetSelector = btn.getAttribute("data-target");
      const input = targetSelector
        ? document.querySelector(targetSelector)
        : btn.closest(".input-group")?.querySelector("input");

      if (!input) return;

      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";

      const icon = btn.querySelector("i");
      if (icon) {
        if (isPassword) {
          icon.classList.remove("fa-eye");
          icon.classList.add("fa-eye-slash");
        } else {
          icon.classList.remove("fa-eye-slash");
          icon.classList.add("fa-eye");
        }
      }

      const label = isPassword ? "Hide password" : "Show password";
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    });
  });
}

/**
 * Self-Introduction ('Tell Me About Yourself') Studio & Practice Coach (#432)
 * Manages 30s/60s/90s pitch length switching, real-time word count & speaking time updates,
 * script customization, and interactive practice evaluation.
 */


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initPasswordToggle();
      initPasswordStrengthIndicator();
    });
  } else {
    initPasswordToggle();
    initPasswordStrengthIndicator();
  }
}
