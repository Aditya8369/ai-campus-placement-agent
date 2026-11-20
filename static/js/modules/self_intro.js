/**
 * Self-Introduction Studio Module (static/js/modules/self_intro.js)
 * ================================================================
 * Generates and customizes elevator pitches, behavioral stories, and practice scripts.
 */

import { escapeHtml, showToast, getCsrfToken, copyToClipboard } from "./utils.js";

export function initSelfIntroductionStudio() {
  const card = document.getElementById("selfIntroSectionCard");
  if (!card) return;

  // Hydrate initial data if available
  let selfIntroData = null;
  try {
    const raw = card.getAttribute("data-self-intro");
    if (raw) {
      selfIntroData = typeof raw === "string" ? JSON.parse(raw) : raw;
    }
  } catch (err) {
    console.warn("Failed to parse initial self-intro data:", err);
  }

  // Active state
  let currentDuration = 30; // 30, 60, or 90
  const scriptsState = {
    30: { script: "", structure: {} },
    60: { script: "", structure: {} },
    90: { script: "", structure: {} }
  };

  if (selfIntroData && selfIntroData.scripts) {
    if (selfIntroData.scripts["30s"]) {
      scriptsState[30].script = selfIntroData.scripts["30s"].script || "";
      scriptsState[30].structure = selfIntroData.scripts["30s"].structure_breakdown || {};
    }
    if (selfIntroData.scripts["60s"]) {
      scriptsState[60].script = selfIntroData.scripts["60s"].script || "";
      scriptsState[60].structure = selfIntroData.scripts["60s"].structure_breakdown || {};
    }
    if (selfIntroData.scripts["90s"]) {
      scriptsState[90].script = selfIntroData.scripts["90s"].script || "";
      scriptsState[90].structure = selfIntroData.scripts["90s"].structure_breakdown || {};
    }
  }

  // DOM Elements
  const lenBtns = card.querySelectorAll(".self-intro-len-btn");
  const scriptEditor = document.getElementById("selfIntroScriptEditor");
  const speakingTimeBadge = document.getElementById("selfIntroSpeakingTime");
  const wordCountBadge = document.getElementById("selfIntroWordCount");
  const focusText = document.getElementById("selfIntroFocusText");
  const btnCopyScript = document.getElementById("btnCopySelfIntroScript");
  const btnLoadPractice = document.getElementById("btnLoadIntoPractice");
  const practiceInput = document.getElementById("selfIntroPracticeInput");
  const practiceStats = document.getElementById("practiceInputStats");
  const btnAnalyzePractice = document.getElementById("btnAnalyzePracticePitch");
  const btnRegenerate = document.getElementById("btnRegenerateSelfIntro");
  const roleInput = document.getElementById("selfIntroRoleInput");
  const companyInput = document.getElementById("selfIntroCompanyInput");

  // Speaking time calculation helper (140 wpm rate)
  function computeLiveStats(text) {
    const words = (text || "").trim().split(/\s+/).filter(Boolean);
    const count = words.length;
    const seconds = count > 0 ? Math.round(count / (140 / 60)) : 0;
    let formatted = `${seconds}s`;
    if (seconds >= 60) {
      const m = Math.floor(seconds / 60);
      const s = seconds % 60;
      formatted = s > 0 ? `${m}m ${s}s` : `${m}m`;
    }
    return { wordCount: count, seconds, formatted };
  }

  // Update UI stats for the active editor
  function updateEditorStats() {
    if (!scriptEditor) return;
    const text = scriptEditor.value;
    scriptsState[currentDuration].script = text;
    const stats = computeLiveStats(text);
    if (speakingTimeBadge) speakingTimeBadge.textContent = stats.formatted;
    if (wordCountBadge) wordCountBadge.textContent = stats.wordCount;
  }

  // Duration length selector buttons
  lenBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      // Save current script before switching
      if (scriptEditor) {
        scriptsState[currentDuration].script = scriptEditor.value;
      }
      lenBtns.forEach((b) => {
        b.classList.remove("btn-primary", "active");
        b.classList.add("btn-outline-secondary");
      });
      btn.classList.remove("btn-outline-secondary");
      btn.classList.add("btn-primary", "active");

      currentDuration = parseInt(btn.getAttribute("data-duration"), 10) || 30;

      // Hydrate editor with target duration's script
      if (scriptEditor) {
        scriptEditor.value = scriptsState[currentDuration].script || "";
      }

      // Update focus hint
      if (focusText) {
        const struct = scriptsState[currentDuration].structure;
        let hint = "Present role, background, and alignment";
        if (struct && struct.present) {
          hint = struct.present;
        } else if (currentDuration === 30) {
          hint = "Present background & core value proposition";
        } else if (currentDuration === 60) {
          hint = "Present foundation & past top project impact";
        } else if (currentDuration === 90) {
          hint = "Full Present-Past-Future narrative with metrics and company alignment";
        }
        focusText.innerHTML = `<strong>Structure Focus:</strong> ${escapeHtml(hint)}`;
      }

      updateEditorStats();
    });
  });

  // Live input listener on the script editor
  if (scriptEditor) {
    scriptEditor.addEventListener("input", updateEditorStats);
  }

  // Copy Pitch to Clipboard
  if (btnCopyScript && scriptEditor) {
    btnCopyScript.addEventListener("click", () => {
      const text = scriptEditor.value.trim();
      if (!text) {
        if (typeof showToast === "function") showToast("Nothing to copy yet", "info");
        return;
      }
      navigator.clipboard.writeText(text).then(() => {
        const originalHtml = btnCopyScript.innerHTML;
        btnCopyScript.innerHTML = '<i class="fa-solid fa-check text-success me-1"></i> Copied!';
        setTimeout(() => {
          btnCopyScript.innerHTML = originalHtml;
        }, 2000);
      }).catch(() => {
        if (typeof showToast === "function") showToast("Failed to copy to clipboard", "error");
      });
    });
  }

  // Load into Practice Coach
  if (btnLoadPractice && practiceInput && scriptEditor) {
    btnLoadPractice.addEventListener("click", () => {
      practiceInput.value = scriptEditor.value;
      updatePracticeStats();
      practiceInput.focus();
      if (typeof showToast === "function") {
        showToast("Loaded pitch into Practice Coach! Adjust and click 'Analyze Pitch'.", "info");
      }
    });
  }

  // Practice input live stats
  function updatePracticeStats() {
    if (!practiceInput || !practiceStats) return;
    const text = practiceInput.value;
    const stats = computeLiveStats(text);
    practiceStats.textContent = `${stats.wordCount} words • ~${stats.formatted} speaking time`;
  }

  if (practiceInput) {
    practiceInput.addEventListener("input", updatePracticeStats);
  }

  // CSRF helper
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  // Regenerate Button Handler
  if (btnRegenerate) {
    btnRegenerate.addEventListener("click", async () => {
      const analysisId = btnRegenerate.getAttribute("data-analysis-id");
      if (!analysisId) return;

      const role = roleInput ? roleInput.value.trim() : "";
      const company = companyInput ? companyInput.value.trim() : "";
      const spinner = document.getElementById("selfIntroSpinner");
      const icon = document.getElementById("selfIntroIcon");

      btnRegenerate.disabled = true;
      if (spinner) spinner.classList.remove("d-none");
      if (icon) icon.classList.add("d-none");

      try {
        const res = await fetch(`/api/self-introduction/${encodeURIComponent(analysisId)}/generate`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
            "X-Requested-With": "XMLHttpRequest"
          },
          body: JSON.stringify({ role_title: role, company_name: company })
        });
        const data = await res.json();
        if (res.ok && data.success && data.data && data.data.scripts) {
          const scripts = data.data.scripts;
          if (scripts["30s"]) {
            scriptsState[30].script = scripts["30s"].script || "";
            scriptsState[30].structure = scripts["30s"].structure_breakdown || {};
          }
          if (scripts["60s"]) {
            scriptsState[60].script = scripts["60s"].script || "";
            scriptsState[60].structure = scripts["60s"].structure_breakdown || {};
          }
          if (scripts["90s"]) {
            scriptsState[90].script = scripts["90s"].script || "";
            scriptsState[90].structure = scripts["90s"].structure_breakdown || {};
          }
          if (scriptEditor) {
            scriptEditor.value = scriptsState[currentDuration].script || "";
            updateEditorStats();
          }
          if (typeof showToast === "function") {
            showToast("Self-introduction scripts updated!", "success");
          }
        } else {
          if (typeof showToast === "function") {
            showToast(data.error || "Failed to regenerate self-introduction", "error");
          }
        }
      } catch (err) {
        console.error("Error regenerating self introduction:", err);
        if (typeof showToast === "function") {
          showToast("Network error while regenerating script.", "error");
        }
      } finally {
        btnRegenerate.disabled = false;
        if (spinner) spinner.classList.add("d-none");
        if (icon) icon.classList.remove("d-none");
      }
    });
  }

  // Analyze Practice Pitch
  if (btnAnalyzePractice) {
    btnAnalyzePractice.addEventListener("click", async () => {
      const analysisId = btnAnalyzePractice.getAttribute("data-analysis-id");
      if (!analysisId || !practiceInput) return;

      const text = practiceInput.value.trim();
      if (!text) {
        if (typeof showToast === "function") {
          showToast("Please enter or paste your practice pitch first.", "warning");
        }
        return;
      }

      const spinner = document.getElementById("practiceSpinner");
      const icon = document.getElementById("practiceIcon");
      const resultsPane = document.getElementById("practiceFeedbackResults");
      const placeholderPane = document.getElementById("practiceFeedbackPlaceholder");

      btnAnalyzePractice.disabled = true;
      if (spinner) spinner.classList.remove("d-none");
      if (icon) icon.classList.add("d-none");

      const role = roleInput ? roleInput.value.trim() : "";
      const company = companyInput ? companyInput.value.trim() : "";

      try {
        const res = await fetch(`/api/self-introduction/${encodeURIComponent(analysisId)}/practice`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
            "X-Requested-With": "XMLHttpRequest"
          },
          body: JSON.stringify({
            practice_text: text,
            target_duration: currentDuration,
            role_title: role,
            company_name: company
          })
        });

        const data = await res.json();
        if (res.ok && data.success && data.evaluation) {
          const evalData = data.evaluation;
          renderPracticeEvaluation(evalData);
          if (placeholderPane) placeholderPane.style.display = "none";
          if (resultsPane) resultsPane.style.display = "block";
          if (typeof showToast === "function") {
            showToast("Practice pitch evaluated successfully!", "success");
          }
        } else {
          if (typeof showToast === "function") {
            showToast(data.error || "Evaluation failed.", "error");
          }
        }
      } catch (err) {
        console.error("Error analyzing practice pitch:", err);
        if (typeof showToast === "function") {
          showToast("Network error while evaluating practice pitch.", "error");
        }
      } finally {
        btnAnalyzePractice.disabled = false;
        if (spinner) spinner.classList.add("d-none");
        if (icon) icon.classList.remove("d-none");
      }
    });
  }

  // Render Practice Feedback Helper
  function renderPracticeEvaluation(ev) {
    const scoreBadge = document.getElementById("practiceClarityScore");
    const verdictBadge = document.getElementById("practiceLengthVerdict");
    const overviewEl = document.getElementById("practiceFeedbackOverview");
    const strengthsEl = document.getElementById("practiceStrengthsList");
    const improvementsEl = document.getElementById("practiceImprovementsList");

    if (scoreBadge) {
      scoreBadge.textContent = `${ev.clarity_score || 85} / 100`;
    }
    if (verdictBadge) {
      verdictBadge.textContent = `${ev.length_verdict || 'Good Pacing'} (${ev.speaking_time_formatted || ''})`;
      if ((ev.length_verdict || "").toLowerCase().includes("ideal") || (ev.length_verdict || "").toLowerCase().includes("good")) {
        verdictBadge.className = "badge bg-success-subtle text-success border rounded-pill";
      } else {
        verdictBadge.className = "badge bg-warning-subtle text-warning border rounded-pill";
      }
    }

    // Structure checklist icons
    const struct = ev.structure_score || {};
    updateCheckmark("badgePresentCheck", struct.has_present);
    updateCheckmark("badgePastCheck", struct.has_past);
    updateCheckmark("badgeFutureCheck", struct.has_future);

    if (overviewEl) {
      overviewEl.textContent = ev.feedback_summary || "";
    }

    if (strengthsEl) {
      const items = ev.strengths || [];
      if (items.length > 0) {
        strengthsEl.innerHTML = `<h6 class="small fw-bold text-success mb-1"><i class="fa-solid fa-thumbs-up me-1"></i> Key Strengths:</h6><ul class="ps-3 mb-2 small text-secondary">${items.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`;
      } else {
        strengthsEl.innerHTML = "";
      }
    }

    if (improvementsEl) {
      const items = ev.improvements || [];
      if (items.length > 0) {
        improvementsEl.innerHTML = `<h6 class="small fw-bold text-warning mb-1"><i class="fa-solid fa-lightbulb me-1"></i> Opportunities to Refine:</h6><ul class="ps-3 mb-0 small text-secondary">${items.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`;
      } else {
        improvementsEl.innerHTML = "";
      }
    }
  }

  function updateCheckmark(elemId, isValid) {
    const el = document.getElementById(elemId);
    if (!el) return;
    if (isValid) {
      el.innerHTML = '<i class="fa-solid fa-circle-check text-success"></i>';
    } else {
      el.innerHTML = '<i class="fa-solid fa-circle-xmark text-danger"></i>';
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
}

/**
 * Project Deep-Dive Interview Practice Mode (#466).
 * Handles project selection, thin project enrichment, grounded question delivery,
 * answer evaluation with scores & improvement tips, and overall session completion.
 */


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSelfIntroductionStudio);
  } else {
    initSelfIntroductionStudio();
  }
}
