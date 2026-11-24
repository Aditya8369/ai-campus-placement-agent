/**
 * Analysis Module (static/js/modules/analysis.js)
 * ===============================================
 * Client-side behaviors for resume upload, validation, SSE/polling pipeline,
 * character counting, and circular score progress dials (#132, #133, #470, #539).
 */

import { escapeHtml } from "./utils.js";
import { handleRateLimitResponse, syncRateLimitFromHeaders, formatCountdown } from "./rate_limit.js";
import { isReducedMotion } from "./motion.js";

/**
 * Real-time character counter and limit monitor for resume text and job description inputs (#132).
 */
export function initCharacterCounters() {
  const resumeInput = document.getElementById("resumeTextInput");
  const resumeCurrent = document.getElementById("resumeCurrentChars");
  const resumeLimitWarning = document.getElementById("resumeCharLimitWarning");
  const resumeMax = 10000;

  const jdInput = document.getElementById("jdInput");
  const jdCurrent = document.getElementById("jdCurrentChars");
  const jdLimitWarning = document.getElementById("jdCharLimitWarning");
  const jdMax = 5000;

  function updateResumeCounter() {
    if (!resumeInput || !resumeCurrent) return;
    const len = resumeInput.value.length;
    resumeCurrent.textContent = len.toLocaleString();

    if (len >= resumeMax) {
      resumeCurrent.classList.add("text-danger", "fw-bold");
      resumeCurrent.classList.remove("text-warning");
      if (resumeLimitWarning) resumeLimitWarning.classList.remove("d-none");
    } else if (len >= resumeMax * 0.9) {
      resumeCurrent.classList.add("text-warning", "fw-bold");
      resumeCurrent.classList.remove("text-danger");
      if (resumeLimitWarning) resumeLimitWarning.classList.remove("d-none");
    } else {
      resumeCurrent.classList.remove("text-danger", "text-warning", "fw-bold");
      if (resumeLimitWarning) resumeLimitWarning.classList.add("d-none");
    }
  }

  function updateJdCounter() {
    if (!jdInput || !jdCurrent) return;
    const len = jdInput.value.length;
    jdCurrent.textContent = len.toLocaleString();

    if (len >= jdMax) {
      jdCurrent.classList.add("text-danger", "fw-bold");
      jdCurrent.classList.remove("text-warning");
      if (jdLimitWarning) jdLimitWarning.classList.remove("d-none");
    } else if (len >= jdMax * 0.9) {
      jdCurrent.classList.add("text-warning", "fw-bold");
      jdCurrent.classList.remove("text-danger");
      if (jdLimitWarning) jdLimitWarning.classList.remove("d-none");
    } else {
      jdCurrent.classList.remove("text-danger", "text-warning", "fw-bold");
      if (jdLimitWarning) jdLimitWarning.classList.add("d-none");
    }
  }

  if (resumeInput) {
    resumeInput.addEventListener("input", updateResumeCounter);
    resumeInput.addEventListener("change", updateResumeCounter);
    resumeInput.addEventListener("paste", () => setTimeout(updateResumeCounter, 0));
    updateResumeCounter();
  }

  if (jdInput) {
    jdInput.addEventListener("input", updateJdCounter);
    jdInput.addEventListener("change", updateJdCounter);
    jdInput.addEventListener("paste", () => setTimeout(updateJdCounter, 0));
    updateJdCounter();
  }

  const form = document.getElementById("analyzeForm") || document.getElementById("analysisForm");
  if (form) {
    form.addEventListener("reset", () => {
      setTimeout(() => {
        updateResumeCounter();
        updateJdCounter();
      }, 0);
    });
  }
}

/**
 * Renders the circular SVG progress dials
 */
export function initCircularProgress() {
  const circles = document.querySelectorAll(".circular-fill-ring");
  const reduced = isReducedMotion();
  circles.forEach((circle) => {
    const score = circle.getAttribute("data-score");
    if (score) {
      const radius = circle.r.baseVal.value;
      const circumference = 2 * Math.PI * radius;
      const offset = circumference - (score / 100) * circumference;

      if (reduced) {
        circle.style.transition = "none";
        circle.style.strokeDasharray = `${circumference} ${circumference}`;
        circle.style.strokeDashoffset = offset;
      } else {
        setTimeout(() => {
          circle.style.strokeDasharray = `${circumference} ${circumference}`;
          circle.style.strokeDashoffset = offset;
        }, 300);
      }
    }
  });
}

/**
 * Initializes resume upload form, drag-and-drop validation, and analysis pipeline (#470, #539).
 */
export function initFormUpload() {
  const uploadForm = document.getElementById("analysisForm");
  if (!uploadForm) return;

  const fileInput = document.getElementById("resumeInput");
  const uploadArea = document.getElementById("uploadArea");
  const progressOverlay = document.getElementById("progressOverlay");
  const fileFeedbackBadge = document.getElementById("fileFeedbackBadge");
  const fileFeedbackBadgeText = document.getElementById("fileFeedbackBadgeText");
  const uploadTypeErrorAlert = document.getElementById("uploadTypeErrorAlert");
  const uploadTypeErrorMessage = document.getElementById("uploadTypeErrorMessage");
  const btnRemoveFile = document.getElementById("btnRemoveFile");
  const uploadIcon = document.getElementById("uploadIcon");
  const uploadPromptText = document.getElementById("uploadPromptText");
  const uploadSubText = document.getElementById("uploadSubText");

  const previewCard = document.getElementById("resumePreviewCard");
  const previewFileName = document.getElementById("previewFileName");
  const previewFileSize = document.getElementById("previewFileSize");
  const previewFileType = document.getElementById("previewFileType");
  const previewFileIcon = document.getElementById("previewFileIcon");
  const resumeEmptyNotice = document.getElementById("resumeEmptyNotice");
  const btnChangeResumeFile = document.getElementById("btnChangeResumeFile");
  const btnDiscardResumePreview = document.getElementById("btnDiscardResumePreview");
  const fileSelectionAnnouncer = document.getElementById("fileSelectionAnnouncer");

  const formatFileSize = (bytes) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const handleSelectedFile = (file) => {
    if (!file) {
      resetUploadArea();
      return;
    }

    const fileName = file.name || "";
    const lowerName = fileName.toLowerCase();
    const isPdf = lowerName.endsWith(".pdf");
    const isDocx = lowerName.endsWith(".docx");

    if (uploadTypeErrorAlert) {
      uploadTypeErrorAlert.classList.add("d-none");
    }

    if (!isPdf && !isDocx) {
      if (uploadTypeErrorAlert && uploadTypeErrorMessage) {
        uploadTypeErrorMessage.textContent = `Unsupported file type "${fileName.split('.').pop() || 'unknown'}". Only .pdf and .docx resume files are supported.`;
        uploadTypeErrorAlert.classList.remove("d-none");
      }
      if (fileSelectionAnnouncer && uploadTypeErrorMessage) {
        fileSelectionAnnouncer.textContent = `Upload error: ${uploadTypeErrorMessage.textContent}`;
      }
      uploadArea.classList.add("border-danger");
      uploadArea.style.backgroundColor = "#fff8f8";
      if (fileInput) fileInput.value = "";
      if (fileFeedbackBadge) fileFeedbackBadge.classList.add("d-none");
      if (previewCard) previewCard.classList.add("d-none");
      if (resumeEmptyNotice) resumeEmptyNotice.classList.remove("d-none");
      return false;
    }

    if (file.size === 0) {
      if (uploadTypeErrorAlert && uploadTypeErrorMessage) {
        uploadTypeErrorMessage.textContent = "The uploaded file is empty. Please upload a valid resume.";
        uploadTypeErrorAlert.classList.remove("d-none");
      }
      if (fileSelectionAnnouncer && uploadTypeErrorMessage) {
        fileSelectionAnnouncer.textContent = `Upload error: ${uploadTypeErrorMessage.textContent}`;
      }
      uploadArea.classList.add("border-danger");
      uploadArea.style.backgroundColor = "#fff8f8";
      if (fileInput) fileInput.value = "";
      if (fileFeedbackBadge) fileFeedbackBadge.classList.add("d-none");
      if (previewCard) previewCard.classList.add("d-none");
      if (resumeEmptyNotice) resumeEmptyNotice.classList.remove("d-none");
      return false;
    }

    const maxUploadBytes = 5 * 1024 * 1024;
    if (file.size > maxUploadBytes) {
      if (uploadTypeErrorAlert && uploadTypeErrorMessage) {
        uploadTypeErrorMessage.textContent = `The uploaded file exceeds the maximum allowed size of 5 MB (${formatFileSize(file.size)}). Please upload a smaller file.`;
        uploadTypeErrorAlert.classList.remove("d-none");
      }
      if (fileSelectionAnnouncer && uploadTypeErrorMessage) {
        fileSelectionAnnouncer.textContent = `Upload error: ${uploadTypeErrorMessage.textContent}`;
      }
      uploadArea.classList.add("border-danger");
      uploadArea.style.backgroundColor = "#fff8f8";
      if (fileInput) fileInput.value = "";
      if (fileFeedbackBadge) fileFeedbackBadge.classList.add("d-none");
      if (previewCard) previewCard.classList.add("d-none");
      if (resumeEmptyNotice) resumeEmptyNotice.classList.remove("d-none");
      return false;
    }

    uploadArea.classList.remove("border-danger");
    uploadArea.style.borderColor = "var(--primary-blue)";
    uploadArea.style.backgroundColor = "var(--secondary-light)";

    const iconClass = isDocx ? "fa-file-word text-primary" : "fa-file-pdf text-danger";
    if (uploadIcon) {
      uploadIcon.className = `fa-solid ${iconClass} upload-icon`;
    }

    if (uploadPromptText) {
      uploadPromptText.innerHTML = `Ready for analysis: <b>${fileName}</b>`;
    }

    if (uploadSubText) {
      uploadSubText.textContent = `File size: ${formatFileSize(file.size)}`;
    }

    if (fileFeedbackBadge && fileFeedbackBadgeText) {
      fileFeedbackBadgeText.innerHTML = `<i class="fa-solid ${iconClass} me-1"></i> ${fileName} (${formatFileSize(file.size)})`;
      fileFeedbackBadge.classList.remove("d-none");
    }

    if (fileSelectionAnnouncer) {
      fileSelectionAnnouncer.textContent = `Resume file ${fileName} selected successfully (${formatFileSize(file.size)}). Ready for analysis.`;
    }

    if (previewCard) {
      if (previewFileName) previewFileName.textContent = fileName;
      if (previewFileSize) previewFileSize.textContent = formatFileSize(file.size);
      if (previewFileType) previewFileType.textContent = isDocx ? "Word Document (.docx)" : "PDF Document (.pdf)";
      if (previewFileIcon) previewFileIcon.className = `fa-solid ${iconClass}`;
      previewCard.classList.remove("d-none");
    }
    if (resumeEmptyNotice) {
      resumeEmptyNotice.classList.add("d-none");
    }

    return true;
  };

  const resetUploadArea = () => {
    if (fileInput) fileInput.value = "";
    if (uploadArea) {
      uploadArea.style.borderColor = "var(--border-color)";
      uploadArea.style.backgroundColor = "#ffffff";
      uploadArea.classList.remove("border-danger", "dragover-active");
    }
    if (uploadIcon) {
      uploadIcon.className = "fa-solid fa-cloud-arrow-up upload-icon";
    }
    if (uploadPromptText) {
      uploadPromptText.textContent = "Drag and drop your resume here, or click to browse";
    }
    if (uploadSubText) {
      uploadSubText.textContent = "Supports .pdf and .docx documents (max 10MB)";
    }
    if (fileFeedbackBadge) {
      fileFeedbackBadge.classList.add("d-none");
    }
    if (uploadTypeErrorAlert) {
      uploadTypeErrorAlert.classList.add("d-none");
    }
    if (previewCard) {
      previewCard.classList.add("d-none");
    }
    if (resumeEmptyNotice) {
      resumeEmptyNotice.classList.remove("d-none");
    }
    if (fileSelectionAnnouncer) {
      fileSelectionAnnouncer.textContent = "Resume file selection cleared.";
    }
  };

  if (uploadArea && fileInput) {
    uploadArea.addEventListener("click", (e) => {
      if (e.target.closest("#btnRemoveFile")) return;
      fileInput.click();
    });

    if (btnRemoveFile) {
      btnRemoveFile.addEventListener("click", (e) => {
        e.stopPropagation();
        resetUploadArea();
      });
    }

    fileInput.addEventListener("change", () => {
      if (fileInput.files.length > 0) {
        handleSelectedFile(fileInput.files[0]);
      } else {
        resetUploadArea();
      }
    });

    if (btnChangeResumeFile) {
      btnChangeResumeFile.addEventListener("click", () => {
        fileInput.click();
      });
    }

    if (btnDiscardResumePreview) {
      btnDiscardResumePreview.addEventListener("click", () => {
        resetUploadArea();
      });
    }

    ["dragenter", "dragover"].forEach((eventName) => {
      uploadArea.addEventListener(
        eventName,
        (e) => {
          e.preventDefault();
          e.stopPropagation();
          uploadArea.classList.add("dragover-active");
          uploadArea.style.borderColor = "var(--primary-blue)";
          uploadArea.style.backgroundColor = "var(--secondary-light)";
        },
        false
      );
    });

    ["dragleave"].forEach((eventName) => {
      uploadArea.addEventListener(
        eventName,
        (e) => {
          e.preventDefault();
          e.stopPropagation();
          uploadArea.classList.remove("dragover-active");
          if (fileInput.files.length === 0) {
            uploadArea.style.borderColor = "var(--border-color)";
            uploadArea.style.backgroundColor = "#ffffff";
          }
        },
        false
      );
    });

    uploadArea.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      uploadArea.classList.remove("dragover-active");
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) {
        const file = files[0];
        fileInput.files = files;
        handleSelectedFile(file);
      }
    });
  }

  const progressTitle = document.getElementById("progressTitle");
  const progressSubtitle = document.getElementById("progressSubtitle");
  const analysisProgressBar = document.getElementById("analysisProgressBar");
  const progressSpinner = document.getElementById("progressSpinner");
  const progressSuccessIcon = document.getElementById("progressSuccessIcon");
  const progressErrorIcon = document.getElementById("progressErrorIcon");
  const progressErrorAlert = document.getElementById("progressErrorAlert");
  const progressErrorMessage = document.getElementById("progressErrorMessage");
  const progressErrorStepName = document.getElementById("progressErrorStepName");
  const btnCloseProgressError = document.getElementById("btnCloseProgressError");
  const btnRetryAnalysis = document.getElementById("btnRetryAnalysis");
  const btnRetryProgress = document.getElementById("btnRetryProgress");
  const btnSubmitAnalysis = document.getElementById("btnSubmitAnalysis");
  const submitBtnSpan = document.getElementById("submitBtnSpan");
  const submitBtnIcon = document.getElementById("submitBtnIcon");
  const btnCancelAnalysis = document.getElementById("btnCancelAnalysis");
  const streamedSectionsContainer = document.getElementById("streamedSectionsContainer");
  const streamedSectionsCounter = document.getElementById("streamedSectionsCounter");
  const streamedSectionsCards = document.getElementById("streamedSectionsCards");
  const btnViewPartialDashboard = document.getElementById("btnViewPartialDashboard");

  let currentTaskId = null;
  let currentAnalysisId = null;
  let cancelUrl = null;
  const receivedSections = new Map();

  let isAnalysisRunning = false;
  let isSubmitting = false;

  function setActionButtonsProcessing(processing) {
    isSubmitting = processing;
    const buttons = uploadForm.querySelectorAll(
      "button[type='submit'], #btnSubmitAnalysis, #btnReviewResumeDirect, #btnClearForm, #btnRetryAnalysis, #btnRetryProgress"
    );
    buttons.forEach((btn) => {
      if (processing) {
        btn.setAttribute("disabled", "true");
        btn.classList.add("disabled");
      } else {
        btn.removeAttribute("disabled");
        btn.classList.remove("disabled");
      }
    });
  }

  function enableSubmitButton() {
    isAnalysisRunning = false;
    setActionButtonsProcessing(false);
    if (btnSubmitAnalysis) {
      btnSubmitAnalysis.disabled = false;
      btnSubmitAnalysis.classList.remove("disabled");
      btnSubmitAnalysis.removeAttribute("aria-disabled");
    }
    if (submitBtnSpan) submitBtnSpan.textContent = "Analyze Readiness";
    if (submitBtnIcon) submitBtnIcon.className = "fa-solid fa-wand-magic-sparkles me-2";
  }

  function disableSubmitButton() {
    isAnalysisRunning = true;
    setActionButtonsProcessing(true);
    if (btnSubmitAnalysis) {
      btnSubmitAnalysis.disabled = true;
      btnSubmitAnalysis.classList.add("disabled");
      btnSubmitAnalysis.setAttribute("aria-disabled", "true");
    }
    if (submitBtnSpan) submitBtnSpan.textContent = "Analyzing...";
    if (submitBtnIcon) submitBtnIcon.className = "spinner-border spinner-border-sm me-2";
  }

  function handleDismissProgressError() {
    if (progressOverlay) {
      progressOverlay.classList.add("d-none");
      progressOverlay.removeAttribute("data-state");
    }
    if (progressSpinner) progressSpinner.classList.remove("d-none");
    if (progressSuccessIcon) progressSuccessIcon.classList.add("d-none");
    if (progressErrorIcon) progressErrorIcon.classList.add("d-none");
    if (progressErrorAlert) progressErrorAlert.classList.add("d-none");
    enableSubmitButton();
  }

  if (btnCloseProgressError) {
    btnCloseProgressError.addEventListener("click", handleDismissProgressError);
  }

  function handleRetryAction() {
    if (btnRetryAnalysis) {
      btnRetryAnalysis.disabled = true;
      btnRetryAnalysis.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Replaying...';
    }
    const retryBadge = document.getElementById("retryRecordStatusBadge");
    if (retryBadge) {
      retryBadge.textContent = "Replaying...";
      retryBadge.className = "badge bg-info text-white rounded-pill px-2 py-1 small";
    }

    if (progressOverlay) progressOverlay.classList.add("d-none");
    if (progressSpinner) progressSpinner.classList.remove("d-none");
    if (progressErrorAlert) progressErrorAlert.classList.add("d-none");
    enableSubmitButton();
    if (uploadForm) {
      uploadForm.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    }
  }

  if (btnRetryAnalysis) {
    btnRetryAnalysis.addEventListener("click", handleRetryAction);
  }
  if (btnRetryProgress) {
    btnRetryProgress.addEventListener("click", handleRetryAction);
  }

  // Handle Cancel Button Action (#465, #764)
  if (btnCancelAnalysis) {
    btnCancelAnalysis.addEventListener("click", () => {
      if (!currentTaskId) return;
      btnCancelAnalysis.disabled = true;
      btnCancelAnalysis.classList.add("disabled");
      btnCancelAnalysis.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Cancelling...';

      const targetCancelUrl = cancelUrl || `/api/analysis/cancel/${currentTaskId}`;
      fetch(targetCancelUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: currentTaskId }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (progressTitle) progressTitle.textContent = "Analysis Cancelled";
          if (progressSubtitle) {
            progressSubtitle.textContent =
              receivedSections.size > 0
                ? `Cancelled by user. ${receivedSections.size} generated section(s) have been kept below.`
                : "Analysis was cancelled. You can adjust your inputs and try again.";
          }
          if (progressSpinner) progressSpinner.classList.add("d-none");
          if (progressErrorIcon) progressErrorIcon.classList.remove("d-none");
          if (btnViewPartialDashboard && currentAnalysisId && receivedSections.size > 0) {
            btnViewPartialDashboard.href = `/dashboard/${currentAnalysisId}`;
            btnViewPartialDashboard.classList.remove("d-none");
          }
          enableSubmitButton();
        })
        .catch((err) => {
          console.warn("Cancel request failed:", err);
          enableSubmitButton();
        });
    });
  }

  // Render streamed section card incrementally as each completes (#764)
  function renderStreamedSection(secName, secData) {
    if (!secName || receivedSections.has(secName)) return;
    receivedSections.set(secName, secData);

    if (streamedSectionsContainer) {
      streamedSectionsContainer.classList.remove("d-none");
    }
    if (streamedSectionsCounter) {
      streamedSectionsCounter.textContent = `${receivedSections.size} ready`;
    }

    if (!streamedSectionsCards) return;

    const card = document.createElement("div");
    card.className = "card border-0 shadow-sm p-3 bg-light rounded-3 text-start mb-2";
    card.id = `streamedCard_${secName}`;

    let title = secName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    let badgeHtml = '<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill small"><i class="fa-solid fa-check me-1"></i> Ready</span>';
    let contentHtml = "";

    if (secName === "resume_analysis") {
      title = "Resume Analysis & ATS";
      const score = secData.ats_score || (secData.ats_breakdown && secData.ats_breakdown.total_score) || 75;
      const strengthsCount = Array.isArray(secData.strengths) ? secData.strengths.length : 0;
      const summary = secData.summary || secData.overall_feedback || "Analysis completed.";
      contentHtml = `
        <div class="d-flex align-items-center justify-content-between mb-1">
          <span class="small fw-semibold text-dark">ATS Score: <strong>${score}/100</strong></span>
          <span class="small text-muted">${strengthsCount} strengths identified</span>
        </div>
        <p class="small text-secondary mb-0 text-truncate" title="${summary}">${summary}</p>
      `;
    } else if (secName === "job_match") {
      title = "Job Description Match";
      const matchPct = secData.match_percentage || 0;
      const matchedCount = Array.isArray(secData.matched_skills) ? secData.matched_skills.length : 0;
      const missingCount = Array.isArray(secData.missing_skills) ? secData.missing_skills.length : 0;
      contentHtml = `
        <div class="d-flex align-items-center justify-content-between mb-1">
          <span class="small fw-semibold text-dark">Role Match: <strong>${matchPct}%</strong></span>
          <span class="small text-muted">${matchedCount} matched, ${missingCount} gaps</span>
        </div>
      `;
    } else if (secName === "skill_gap") {
      title = "Skill Gap Assessment";
      const gapsCount = Array.isArray(secData) ? secData.length : 0;
      contentHtml = `
        <span class="small fw-semibold text-dark">${gapsCount} prioritized skill gaps identified with resources</span>
      `;
    } else if (secName === "learning_roadmap") {
      title = "6-Week Preparation Roadmap";
      const weeksCount = Array.isArray(secData) ? secData.length : 6;
      contentHtml = `
        <span class="small fw-semibold text-dark">${weeksCount}-week structured preparation roadmap with coding tasks</span>
      `;
    } else if (secName === "interview_questions") {
      title = "Company Interview Questions";
      const hrCount = secData.hr ? secData.hr.length : 0;
      const techCount = secData.technical ? secData.technical.length : 0;
      const behCount = secData.behavioral ? secData.behavioral.length : 0;
      contentHtml = `
        <span class="small fw-semibold text-dark">${hrCount + techCount + behCount} customized interview questions (Technical, HR, Behavioral) generated</span>
      `;
    } else {
      contentHtml = `<p class="small text-secondary mb-0">${typeof secData === "string" ? secData : "Section generated."}</p>`;
    }

    card.innerHTML = `
      <div class="d-flex align-items-center justify-content-between mb-1">
        <strong class="small text-primary"><i class="fa-solid fa-file-lines me-1"></i> ${title}</strong>
        ${badgeHtml}
      </div>
      ${contentHtml}
    `;

    streamedSectionsCards.appendChild(card);
    streamedSectionsCards.scrollTop = streamedSectionsCards.scrollHeight;
  }

  const stepOrder = ["step1", "step2", "step3", "step4", "step5", "step6"];
  const stepNamesMap = {
    "step1": "Reading resume",
    "step2": "Checking format",
    "step3": "Matching job description",
    "step4": "Finding skill gaps",
    "step5": "Building roadmap",
    "step6": "Preparing interview questions"
  };

  function resetProgressPanel() {
    if (streamedSectionsCards) streamedSectionsCards.innerHTML = "";
    if (streamedSectionsContainer) streamedSectionsContainer.classList.add("d-none");
    if (streamedSectionsCounter) streamedSectionsCounter.textContent = "0 ready";
    if (btnViewPartialDashboard) btnViewPartialDashboard.classList.add("d-none");
    if (btnCancelAnalysis) {
      btnCancelAnalysis.disabled = false;
      btnCancelAnalysis.classList.remove("disabled");
      btnCancelAnalysis.innerHTML = '<i class="fa-solid fa-ban me-1"></i> Cancel Analysis';
    }
    receivedSections.clear();

    if (progressOverlay) progressOverlay.removeAttribute("data-state");
    if (progressSpinner) progressSpinner.classList.remove("d-none");
    if (progressSuccessIcon) progressSuccessIcon.classList.add("d-none");
    if (progressErrorIcon) progressErrorIcon.classList.add("d-none");
    if (progressErrorAlert) progressErrorAlert.classList.add("d-none");
    if (progressTitle) progressTitle.textContent = "Coordinating AI Agents";
    if (progressSubtitle) progressSubtitle.textContent = "Orchestrating multi-agent analysis in progress...";
    const progressAnnouncer = document.getElementById("progressLiveAnnouncer");
    if (progressAnnouncer) progressAnnouncer.textContent = "Multi-agent placement analysis started. Please stand by.";
    if (analysisProgressBar) {
      analysisProgressBar.style.width = "5%";
      analysisProgressBar.setAttribute("aria-valuenow", "5");
      analysisProgressBar.className = "progress-bar progress-bar-striped progress-bar-animated bg-primary";
    }

    stepOrder.forEach((stepId, idx) => {
      const el = document.getElementById(stepId);
      if (el) {
        el.className = "progress-step text-muted";
        const ind = el.querySelector(".step-indicator");
        if (ind) {
          ind.textContent = String(idx + 1);
          ind.setAttribute("aria-label", `Step ${idx + 1}: ${stepNamesMap[stepId]} (Pending)`);
        }
      }
    });
  }

  function startPolling(statusUrl, onMilestone, onError) {
    if (!statusUrl) return;
    let pollCount = 0;
    const maxPolls = 120;
    const pollInterval = setInterval(async () => {
      pollCount++;
      try {
        const res = await fetch(statusUrl);
        if (!res.ok) throw new Error("Status check failed");
        const statusData = await res.json();

        if (statusData.milestones && statusData.milestones.length > 0) {
          const latest = statusData.milestones[statusData.milestones.length - 1];
          onMilestone(latest);
        }

        if (statusData.status === "completed") {
          clearInterval(pollInterval);
          onMilestone({
            status: "completed",
            step: "completed",
            current_step_name: "Completed",
            completed_steps: statusData.completed_steps || [],
            progress: 100,
            redirect_url: statusData.redirect_url,
            message: "Multi-agent placement analysis complete! Redirecting..."
          });
        } else if (statusData.status === "error") {
          clearInterval(pollInterval);
          const failedStep = statusData.failed_step || statusData.current_step_name;
          onError(statusData.error_message || "Analysis pipeline encountered an error.", failedStep);
        } else if (pollCount >= maxPolls) {
          clearInterval(pollInterval);
          onError("Analysis pipeline timed out. Please try again.");
        }
      } catch (err) {
        if (pollCount >= maxPolls) {
          clearInterval(pollInterval);
          onError("Failed to poll analysis status: " + err.message);
        }
      }
    }, 1000);
  }

  const DRAFT_STORAGE_KEY = "placement_analysis_form_draft_v1";
  const DRAFT_MAX_AGE_MS = 48 * 60 * 60 * 1000; // 48 hours

  const draftRestoredAlert = document.getElementById("draftRestoredAlert");
  const draftRestoredTimeText = document.getElementById("draftRestoredTimeText");
  const btnDiscardDraft = document.getElementById("btnDiscardDraft");
  const btnCloseDraftAlert = document.getElementById("btnCloseDraftAlert");
  const analysisDraftStatusBadge = document.getElementById("analysisDraftStatusBadge");
  const analysisDraftStatusText = document.getElementById("analysisDraftStatusText");
  const resumeDraftPrivacyWarning = document.getElementById("resumeDraftPrivacyWarning");

  let draftIndicatorTimeout = null;
  let draftAutosaveDebounce = null;

  function setDraftBadge(message, isVisible = true) {
    if (!analysisDraftStatusBadge) return;
    if (draftIndicatorTimeout) clearTimeout(draftIndicatorTimeout);
    if (!isVisible) {
      analysisDraftStatusBadge.classList.add("d-none");
      return;
    }
    if (analysisDraftStatusText) analysisDraftStatusText.textContent = message;
    analysisDraftStatusBadge.classList.remove("d-none");
    analysisDraftStatusBadge.classList.add("d-inline-flex");
    draftIndicatorTimeout = setTimeout(() => {
      analysisDraftStatusBadge.classList.add("d-none");
      analysisDraftStatusBadge.classList.remove("d-inline-flex");
    }, 3000);
  }

  function getFormDraftPayload() {
    const resumeTextEl = document.getElementById("resumeTextInput");
    const jdInputEl = document.getElementById("jdInput");
    const roleSelectEl = document.getElementById("roleTemplateSelect");
    const companySelectEl = document.getElementById("companySelect");
    const studentIdEl = document.getElementById("studentIdInput");
    const analysisModeEl = document.getElementById("analysisModeInput");
    const reviewSwitchEl = document.getElementById("reviewStepSwitch");
    const consentCheckEl = document.getElementById("privacyConsentCheck");

    const batchSelected = [];
    const batchChecks = uploadForm.querySelectorAll(".company-pill-check:checked");
    batchChecks.forEach((c) => batchSelected.push(c.value));

    const activeTab = document.querySelector("#resumeTab .nav-link.active");
    const activeTabId = activeTab ? activeTab.id : "pdf-tab";

    return {
      timestamp: Date.now(),
      active_tab: activeTabId,
      resume_text: resumeTextEl ? resumeTextEl.value : "",
      job_description: jdInputEl ? jdInputEl.value : "",
      role_template: roleSelectEl ? roleSelectEl.value : "",
      company: companySelectEl ? companySelectEl.value : "General",
      student_id: studentIdEl ? studentIdEl.value : "",
      analysis_mode: analysisModeEl ? analysisModeEl.value : "role",
      batch_mode: batchModeSwitch ? batchModeSwitch.checked : false,
      batch_companies: batchSelected,
      review_step: reviewSwitchEl ? reviewSwitchEl.checked : false,
      privacy_consent: consentCheckEl ? consentCheckEl.checked : false,
    };
  }

  function hasSubstantialDraftContent(draft) {
    if (!draft) return false;
    const hasResumeText = (draft.resume_text || "").trim().length > 0;
    const hasJd = (draft.job_description || "").trim().length > 0;
    const hasRole = Boolean(draft.role_template);
    const hasCustomCompany = draft.company && draft.company !== "General";
    const hasStudentId = (draft.student_id || "").trim().length > 0;
    const hasBatch = Boolean(draft.batch_mode);
    return hasResumeText || hasJd || hasRole || hasCustomCompany || hasStudentId || hasBatch;
  }

  function saveFormDraft() {
    try {
      const draft = getFormDraftPayload();
      // Update pasted resume privacy warning
      if (resumeDraftPrivacyWarning) {
        if ((draft.resume_text || "").trim().length > 10) {
          resumeDraftPrivacyWarning.classList.remove("d-none");
        } else {
          resumeDraftPrivacyWarning.classList.add("d-none");
        }
      }

      if (!hasSubstantialDraftContent(draft)) {
        // Nothing meaningful to store; remove draft if present
        localStorage.removeItem(DRAFT_STORAGE_KEY);
        return;
      }

      localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      setDraftBadge("Draft saved locally");
    } catch (err) {
      console.warn("Unable to save analysis form draft to localStorage:", err);
    }
  }

  function clearFormDraft() {
    try {
      localStorage.removeItem(DRAFT_STORAGE_KEY);
      if (draftRestoredAlert) draftRestoredAlert.classList.add("d-none");
      if (analysisDraftStatusBadge) analysisDraftStatusBadge.classList.add("d-none");
      if (resumeDraftPrivacyWarning) resumeDraftPrivacyWarning.classList.add("d-none");
    } catch (err) {
      console.warn("Unable to clear analysis form draft:", err);
    }
  }

  function restoreFormDraft() {
    try {
      const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw);
      if (!draft || !draft.timestamp) return;

      // Expire draft if older than 48 hours
      if (Date.now() - draft.timestamp > DRAFT_MAX_AGE_MS) {
        localStorage.removeItem(DRAFT_STORAGE_KEY);
        return;
      }

      if (!hasSubstantialDraftContent(draft)) {
        localStorage.removeItem(DRAFT_STORAGE_KEY);
        return;
      }

      // Restore form fields
      const resumeTextEl = document.getElementById("resumeTextInput");
      if (resumeTextEl && draft.resume_text) {
        resumeTextEl.value = draft.resume_text;
        resumeTextEl.dispatchEvent(new Event("input", { bubbles: true }));
        if (resumeDraftPrivacyWarning) resumeDraftPrivacyWarning.classList.remove("d-none");
      }

      const jdInputEl = document.getElementById("jdInput");
      if (jdInputEl && draft.job_description) {
        jdInputEl.value = draft.job_description;
        jdInputEl.dispatchEvent(new Event("input", { bubbles: true }));
      }

      const roleSelectEl = document.getElementById("roleTemplateSelect");
      if (roleSelectEl && draft.role_template) {
        roleSelectEl.value = draft.role_template;
        roleSelectEl.dispatchEvent(new Event("change", { bubbles: true }));
      }

      const companySelectEl = document.getElementById("companySelect");
      if (companySelectEl && draft.company) {
        companySelectEl.value = draft.company;
      }

      const studentIdEl = document.getElementById("studentIdInput");
      if (studentIdEl && draft.student_id) {
        studentIdEl.value = draft.student_id;
      }

      const analysisModeEl = document.getElementById("analysisModeInput");
      const btnModeRole = document.getElementById("btnModeRole");
      const btnModeJd = document.getElementById("btnModeJd");
      const roleSection = document.getElementById("roleTemplateSection");
      const customJdSection = document.getElementById("customJdSection");

      if (draft.analysis_mode === "jd" && btnModeJd) {
        btnModeJd.click();
      } else if (draft.analysis_mode === "role" && btnModeRole) {
        btnModeRole.click();
      }

      if (batchModeSwitch && draft.batch_mode) {
        batchModeSwitch.checked = true;
        batchModeSwitch.dispatchEvent(new Event("change"));
        if (draft.batch_companies && Array.isArray(draft.batch_companies)) {
          const companyPills = document.querySelectorAll(".company-pill-badge");
          companyPills.forEach((pill) => {
            const chk = pill.querySelector(".company-pill-check");
            if (chk) {
              chk.checked = draft.batch_companies.includes(chk.value);
              if (chk.checked) pill.classList.add("active");
              else pill.classList.remove("active");
            }
          });
        }
      }

      const reviewSwitchEl = document.getElementById("reviewStepSwitch");
      if (reviewSwitchEl && typeof draft.review_step === "boolean") {
        reviewSwitchEl.checked = draft.review_step;
      }

      const consentCheckEl = document.getElementById("privacyConsentCheck");
      if (consentCheckEl && draft.privacy_consent) {
        consentCheckEl.checked = true;
      }

      if (draft.active_tab === "text-tab") {
        const textTab = document.getElementById("text-tab");
        if (textTab) {
          if (window.bootstrap && window.bootstrap.Tab) {
            window.bootstrap.Tab.getOrCreateInstance(textTab).show();
          } else {
            textTab.click();
          }
        }
      }

      // Display draft restored banner
      if (draftRestoredAlert) {
        if (draftRestoredTimeText) {
          const savedDate = new Date(draft.timestamp);
          const timeFormatted = savedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          draftRestoredTimeText.textContent = `Unfinished inputs saved at ${timeFormatted} were restored. You can continue editing or discard the draft.`;
        }
        draftRestoredAlert.classList.remove("d-none");
      }
      setDraftBadge("Draft restored");
    } catch (err) {
      console.warn("Unable to restore analysis form draft:", err);
    }
  }

  // Restore on initialization
  restoreFormDraft();

  // Setup draft auto-save listeners on inputs
  const draftInputSelectors = "#resumeTextInput, #jdInput, #studentIdInput, #companySelect, #roleTemplateSelect, #privacyConsentCheck, #reviewStepSwitch";
  uploadForm.querySelectorAll(draftInputSelectors).forEach((inputEl) => {
    const evtType = (inputEl.tagName === "SELECT" || inputEl.type === "checkbox") ? "change" : "input";
    inputEl.addEventListener(evtType, () => {
      if (draftAutosaveDebounce) clearTimeout(draftAutosaveDebounce);
      draftAutosaveDebounce = setTimeout(saveFormDraft, 800);
    });
  });

  // Periodic autosave every 4 seconds when user is actively editing
  const draftPeriodicInterval = setInterval(saveFormDraft, 4000);

  // Before unload listener to save last-second edits
  window.addEventListener("beforeunload", () => {
    saveFormDraft();
  });

  // Discard draft button handler
  if (btnDiscardDraft) {
    btnDiscardDraft.addEventListener("click", () => {
      clearFormDraft();
      if (btnClearForm) {
        btnClearForm.click();
      }
    });
  }

  if (btnCloseDraftAlert && draftRestoredAlert) {
    btnCloseDraftAlert.addEventListener("click", () => {
      draftRestoredAlert.classList.add("d-none");
    });
  }

  // Hook clearFormDraft to window for tests and consumers
  if (typeof window !== "undefined") {
    window.clearAnalysisFormDraft = clearFormDraft;
    window.saveAnalysisFormDraft = saveFormDraft;
    window.restoreAnalysisFormDraft = restoreFormDraft;
  }

  const batchModeSwitch = document.getElementById("batchModeSwitch");
  const singleCompanyContainer = document.getElementById("singleCompanyContainer");
  const batchCompanyContainer = document.getElementById("batchCompanyContainer");
  const batchSubmitSpan = uploadForm.querySelector("button[type='submit'] span");
  const batchSubmitIcon = uploadForm.querySelector("button[type='submit'] i");

  if (batchModeSwitch) {
    batchModeSwitch.addEventListener("change", () => {
      const isBatch = batchModeSwitch.checked;
      if (isBatch) {
        if (singleCompanyContainer) singleCompanyContainer.classList.add("d-none");
        if (batchCompanyContainer) batchCompanyContainer.classList.remove("d-none");
        if (batchSubmitSpan) batchSubmitSpan.textContent = "Compare Companies & Offer Matrix";
        if (batchSubmitIcon) batchSubmitIcon.className = "fa-solid fa-chart-pie me-2";
      } else {
        if (singleCompanyContainer) singleCompanyContainer.classList.remove("d-none");
        if (batchCompanyContainer) batchCompanyContainer.classList.add("d-none");
        if (batchSubmitSpan) batchSubmitSpan.textContent = "Analyze Readiness";
        if (batchSubmitIcon) batchSubmitIcon.className = "fa-solid fa-wand-magic-sparkles me-2";
      }
    });
  }

  const companyPills = document.querySelectorAll(".company-pill-badge");
  companyPills.forEach((pill) => {
    const chk = pill.querySelector(".company-pill-check");
    pill.addEventListener("click", (e) => {
      if (e.target !== chk) {
        chk.checked = !chk.checked;
      }
      if (chk.checked) {
        pill.classList.add("active");
      } else {
        pill.classList.remove("active");
      }
    });
    if (chk && chk.checked) {
      pill.classList.add("active");
    }
  });

  const btnSelectAllBatch = document.getElementById("btnSelectAllBatch");
  if (btnSelectAllBatch) {
    btnSelectAllBatch.addEventListener("click", () => {
      companyPills.forEach((pill, idx) => {
        const chk = pill.querySelector(".company-pill-check");
        if (chk) {
          chk.checked = idx < 4;
          if (chk.checked) pill.classList.add("active");
          else pill.classList.remove("active");
        }
      });
    });
  }

  const btnClearAllBatch = document.getElementById("btnClearAllBatch");
  if (btnClearAllBatch) {
    btnClearAllBatch.addEventListener("click", () => {
      companyPills.forEach((pill) => {
        const chk = pill.querySelector(".company-pill-check");
        if (chk) {
          chk.checked = false;
          pill.classList.remove("active");
        }
      });
    });
  }

  const btnClearForm = document.getElementById("btnClearForm");
  const formResetAlert = document.getElementById("formResetAlert");
  const formResetAlertMessage = document.getElementById("formResetAlertMessage");
  const btnCloseResetAlert = document.getElementById("btnCloseResetAlert");

  if (btnCloseResetAlert && formResetAlert) {
    btnCloseResetAlert.addEventListener("click", () => {
      formResetAlert.classList.add("d-none");
    });
  }

  if (btnClearForm) {
    btnClearForm.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      const resumeTextInput = document.getElementById("resumeTextInput");
      if (resumeTextInput) {
        resumeTextInput.value = "";
      }

      resetUploadArea();

      const jdInput = document.getElementById("jdInput");
      if (jdInput) {
        jdInput.value = "";
      }

      const companySelect = document.getElementById("companySelect");
      if (companySelect) {
        companySelect.value = "General";
      }

      const studentIdInput = document.getElementById("studentIdInput");
      if (studentIdInput) {
        studentIdInput.value = "";
      }

      if (batchModeSwitch && batchModeSwitch.checked) {
        batchModeSwitch.checked = false;
        batchModeSwitch.dispatchEvent(new Event("change"));
      }

      const reviewStepSwitch = document.getElementById("reviewStepSwitch");
      if (reviewStepSwitch && reviewStepSwitch.checked) {
        reviewStepSwitch.checked = false;
      }

      const privacyConsentCheck = document.getElementById("privacyConsentCheck");
      if (privacyConsentCheck) {
        privacyConsentCheck.checked = false;
      }

      const pdfTab = document.getElementById("pdf-tab");
      if (pdfTab) {
        if (window.bootstrap && window.bootstrap.Tab) {
          const tabInstance = window.bootstrap.Tab.getOrCreateInstance(pdfTab);
          tabInstance.show();
        } else {
          pdfTab.click();
        }
      }

      if (formResetAlert) {
        if (formResetAlertMessage) {
          formResetAlertMessage.textContent = "Form cleared successfully. All inputs have been reset.";
        }
        formResetAlert.classList.remove("d-none");
        formResetAlert.scrollIntoView({ behavior: isReducedMotion() ? "auto" : "smooth", block: "nearest" });

        clearTimeout(window._formResetAlertTimeout);
        window._formResetAlertTimeout = setTimeout(() => {
          formResetAlert.classList.add("d-none");
        }, 4000);
      }

      clearFormDraft();
    });
  }

  const btnReviewResumeDirect = document.getElementById("btnReviewResumeDirect");
  if (btnReviewResumeDirect) {
    btnReviewResumeDirect.addEventListener("click", () => {
      if (isSubmitting) return;

      const textInput = document.getElementById("resumeTextInput");
      const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
      const hasText = textInput && textInput.value.trim().length > 0;

      if (!hasFile && !hasText) {
        alert("Please upload a PDF or DOCX resume, or paste your resume text first to review extracted info.");
        return;
      }

      const consentCheck = document.getElementById("privacyConsentCheck");
      if (consentCheck && !consentCheck.checked) {
        alert("Please agree to the privacy notice and consent to data processing before analyzing your resume.");
        consentCheck.focus();
        return;
      }

      setActionButtonsProcessing(true);
      const reviewSwitch = document.getElementById("reviewStepSwitch");
      if (reviewSwitch) reviewSwitch.checked = true;
      uploadForm.action = "/resume/review";
      uploadForm.submit();
    });
  }

  uploadForm.addEventListener("submit", (e) => {
    e.preventDefault();

    if (isSubmitting) return;
    if (isAnalysisRunning) return false;

    const textInput = document.getElementById("resumeTextInput");
    const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
    const hasText = textInput && textInput.value.trim().length > 0;

    if (!hasFile && !hasText) {
      alert("Please upload a PDF or DOCX resume, or paste your resume text first.");
      return;
    }

    const consentCheck = document.getElementById("privacyConsentCheck");
    if (consentCheck && !consentCheck.checked) {
      alert("Please agree to the privacy notice and consent to data processing before analyzing your resume.");
      consentCheck.focus();
      return;
    }

    setActionButtonsProcessing(true);

    const reviewStepSwitch = document.getElementById("reviewStepSwitch");
    if (reviewStepSwitch && reviewStepSwitch.checked) {
      uploadForm.action = "/resume/review";
      uploadForm.submit();
      return;
    }

    disableSubmitButton();

    if (batchModeSwitch && batchModeSwitch.checked) {
      const selectedChecks = uploadForm.querySelectorAll(".company-pill-check:checked");
      if (selectedChecks.length === 0) {
        enableSubmitButton();
        alert("Please select at least one company to compare.");
        return;
      }

      resetProgressPanel();
      if (progressOverlay) progressOverlay.classList.remove("d-none");
      if (progressTitle) progressTitle.textContent = "Multi-Company Batch Comparison";
      if (progressSubtitle) progressSubtitle.textContent = "Evaluating candidate profile across selected recruiters in background workers...";
      if (analysisProgressBar) {
        analysisProgressBar.style.width = "40%";
        analysisProgressBar.setAttribute("aria-valuenow", "40");
      }

      const formData = new FormData(uploadForm);
      fetch("/api/analysis/batch-compare", {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok || !data.success) {
            throw new Error(data.error || "Batch comparison failed.");
          }
          if (progressOverlay) progressOverlay.setAttribute("data-state", "success");
          if (analysisProgressBar) {
            analysisProgressBar.style.width = "100%";
            analysisProgressBar.className = "progress-bar bg-success";
          }
          if (progressSpinner) progressSpinner.classList.add("d-none");
          if (progressSuccessIcon) progressSuccessIcon.classList.remove("d-none");
          if (progressTitle) progressTitle.textContent = "Comparison Complete!";
          if (progressSubtitle) progressSubtitle.textContent = "Redirecting to your Company Comparison Matrix...";
          clearFormDraft();
          setTimeout(() => {
            window.location.href = data.redirect_url;
          }, 500);
        })
        .catch((err) => {
          enableSubmitButton();
          showPipelineError(err.message || "An unexpected error occurred during batch comparison.", "Batch Comparison");
        });
      return;
    }

    resetProgressPanel();
    if (progressOverlay) progressOverlay.classList.remove("d-none");

    let eventSource = null;

    function handleMilestone(milestone) {
      const step = milestone.step;
      const progress = milestone.progress || 0;
      const message = milestone.message || "";
      const status = milestone.status;
      const stepName = milestone.current_step_name || stepNamesMap[step] || step;
      const completedSteps = milestone.completed_steps || [];

      // Check for streaming section completed event (#764)
      if (
        milestone.event === "section_completed" ||
        milestone.step === "section_stream" ||
        milestone.section ||
        (milestone.extra && (milestone.extra.section || milestone.extra.event === "section_completed"))
      ) {
        const secName =
          milestone.section ||
          (milestone.extra && (milestone.extra.section || milestone.extra.section_name));
        const secData =
          milestone.data ||
          milestone.section_data ||
          (milestone.extra && (milestone.extra.data || milestone.extra.section_data));
        if (secName && secData) {
          renderStreamedSection(secName, secData);
        }
      }

      if (status === "cancelled" || step === "cancelled") {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        if (progressTitle) progressTitle.textContent = "Analysis Cancelled";
        if (progressSubtitle) {
          progressSubtitle.textContent =
            receivedSections.size > 0
              ? `Analysis stopped. ${receivedSections.size} generated section(s) are preserved below.`
              : (milestone.message || "Analysis was cancelled by the user.");
        }
        if (progressSpinner) progressSpinner.classList.add("d-none");
        if (progressErrorIcon) progressErrorIcon.classList.remove("d-none");
        if (btnViewPartialDashboard && currentAnalysisId && receivedSections.size > 0) {
          btnViewPartialDashboard.href = `/dashboard/${currentAnalysisId}`;
          btnViewPartialDashboard.classList.remove("d-none");
        }
        enableSubmitButton();
        return;
      }

      if (analysisProgressBar) {
        analysisProgressBar.style.width = `${progress}%`;
        analysisProgressBar.setAttribute("aria-valuenow", String(progress));
      }

      if (progressSubtitle && message) {
        progressSubtitle.textContent = message;
      }

      const progressAnnouncer = document.getElementById("progressLiveAnnouncer");
      if (progressAnnouncer) {
        if (status === "completed" || step === "completed") {
          progressAnnouncer.textContent = "Analysis complete! Redirecting to your dashboard...";
        } else if (status === "error" || step === "error") {
          const failedStepName = milestone.failed_step || stepName;
          progressAnnouncer.textContent = `Analysis error during ${failedStepName}: ${message}`;
        } else if (stepName) {
          progressAnnouncer.textContent = `Current step: ${stepName} (${progress}%). ${message}`;
        }
      }

      if (step && step.startsWith("step")) {
        const currentIdx = stepOrder.indexOf(step);
        stepOrder.forEach((sId, idx) => {
          const el = document.getElementById(sId);
          if (!el) return;
          const ind = el.querySelector(".step-indicator");
          const sName = stepNamesMap[sId];
          const isCompleted = completedSteps.includes(sName) || (currentIdx > -1 && idx < currentIdx);

          if (isCompleted) {
            el.className = "progress-step completed";
            if (ind) {
              ind.innerHTML = "✓";
              ind.setAttribute("aria-label", `Step ${idx + 1}: ${sName} (Completed)`);
            }
          } else if (idx === currentIdx) {
            el.className = "progress-step active";
            if (ind) {
              ind.textContent = String(idx + 1);
              ind.setAttribute("aria-label", `Step ${idx + 1}: ${sName} (In progress)`);
            }
          } else {
            el.className = "progress-step text-muted";
            if (ind) {
              ind.textContent = String(idx + 1);
              ind.setAttribute("aria-label", `Step ${idx + 1}: ${sName} (Pending)`);
            }
          }
        });
      }

      if (status === "completed" || step === "completed") {
        stepOrder.forEach((sId, idx) => {
          const el = document.getElementById(sId);
          if (el) {
            el.className = "progress-step completed";
            const ind = el.querySelector(".step-indicator");
            if (ind) {
              ind.innerHTML = "✓";
              ind.setAttribute("aria-label", `Step ${idx + 1}: ${stepNamesMap[sId]} (Completed)`);
            }
          }
        });

        if (progressOverlay) progressOverlay.setAttribute("data-state", "success");
        if (progressSpinner) progressSpinner.classList.add("d-none");
        if (progressSuccessIcon) progressSuccessIcon.classList.remove("d-none");
        if (progressErrorIcon) progressErrorIcon.classList.add("d-none");

        if (analysisProgressBar) {
          analysisProgressBar.style.width = "100%";
          analysisProgressBar.setAttribute("aria-valuenow", "100");
          analysisProgressBar.className = "progress-bar bg-success";
          analysisProgressBar.classList.remove("progress-bar-animated");
        }
        if (progressTitle) progressTitle.textContent = "Analysis Complete!";
        if (progressSubtitle) progressSubtitle.textContent = "Redirecting to your comprehensive placement dashboard...";
        clearFormDraft();

        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }

        const redirectUrl =
          milestone.redirect_url || (milestone.extra && milestone.extra.redirect_url) || "/";
        setTimeout(() => {
          window.location.href = redirectUrl;
        }, 500);
      } else if (status === "error" || step === "error") {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        const failedStepName = milestone.failed_step || milestone.current_step_name || stepNamesMap[step];
        showPipelineError(
          milestone.message || "An unexpected error occurred during multi-agent analysis.",
          failedStepName,
          step
        );
      }
    }

    function showPipelineError(errMsg, failedStepName, failedStepKey) {
      enableSubmitButton();
      if (progressOverlay) progressOverlay.setAttribute("data-state", "error");
      if (progressSpinner) progressSpinner.classList.add("d-none");
      if (progressErrorIcon) progressErrorIcon.classList.remove("d-none");
      const stepLabel = failedStepName || "Resume Analysis";

      const progressAnnouncer = document.getElementById("progressLiveAnnouncer");
      if (progressAnnouncer) {
        progressAnnouncer.textContent = `Analysis error during ${stepLabel}: ${errMsg}`;
      }

      if (failedStepKey && stepOrder.includes(failedStepKey)) {
        const el = document.getElementById(failedStepKey);
        if (el) {
          el.className = "progress-step failed text-danger";
          const ind = el.querySelector(".step-indicator");
          if (ind) {
            ind.innerHTML = "✕";
            ind.setAttribute("aria-label", `${stepLabel} (Failed)`);
          }
        }
      } else if (failedStepName) {
        stepOrder.forEach((sId) => {
          if (stepNamesMap[sId] === failedStepName) {
            const el = document.getElementById(sId);
            if (el) {
              el.className = "progress-step failed text-danger";
              const ind = el.querySelector(".step-indicator");
              if (ind) {
                ind.innerHTML = "✕";
                ind.setAttribute("aria-label", `${failedStepName} (Failed)`);
              }
            }
          }
        });
      }

      if (progressErrorStepName) {
        progressErrorStepName.textContent = stepLabel;
      }

      // Errors never discard content that was already shown (#764)
      let displayMsg = errMsg;
      if (receivedSections.size > 0) {
        displayMsg = `${errMsg} (${receivedSections.size} section(s) generated before this issue are kept below).`;
        if (progressSubtitle) {
          progressSubtitle.textContent = `Interrupted, but ${receivedSections.size} completed section(s) are preserved below.`;
        }
        if (btnViewPartialDashboard && currentAnalysisId) {
          btnViewPartialDashboard.href = `/dashboard/${currentAnalysisId}`;
          btnViewPartialDashboard.classList.remove("d-none");
        }
      }

      if (progressErrorAlert && progressErrorMessage) {
        progressErrorMessage.textContent = displayMsg;
        progressErrorAlert.classList.remove("d-none");

        const retryBadge = document.getElementById("retryRecordStatusBadge");
        const retryMeta = document.getElementById("retryRecordMetaInfo");
        const retryExpiry = document.getElementById("retryRecordExpiryText");
        const retryAttempts = document.getElementById("retryRecordAttemptsText");

        if (retryBadge) {
          retryBadge.classList.remove("d-none");
          retryBadge.textContent = "Ready to Replay";
          retryBadge.className = "badge bg-warning-subtle text-warning border border-warning-subtle rounded-pill px-2 py-1 small";
        }
        if (retryMeta) {
          retryMeta.classList.remove("d-none");
          if (retryExpiry) retryExpiry.textContent = "Expires in 15m";
          if (retryAttempts) retryAttempts.textContent = "Attempt 0 of 3";
        }

        // Asynchronously save safe retry record to server
        fetch("/api/retry-records", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_type: "analysis_run",
            endpoint: "/api/analysis/start",
            http_method: "POST",
            payload: {
              company: uploadForm?.querySelector("[name='company']")?.value || "",
              target_role: uploadForm?.querySelector("[name='target_role']")?.value || ""
            },
            error_message: `Failed at ${stepLabel}: ${displayMsg}`,
            ttl_seconds: 900
          })
        }).then(r => r.json()).then(res => {
          if (res.success && res.record) {
            const rec = res.record;
            if (retryBadge) {
              retryBadge.textContent = rec.status === "failed" ? "Ready to Replay" : rec.status;
            }
            if (retryExpiry) {
              const mins = Math.max(1, Math.round((rec.seconds_until_expiry || 900) / 60));
              retryExpiry.textContent = `Expires in ${mins}m`;
            }
            if (retryAttempts) {
              retryAttempts.textContent = `Attempt ${rec.retry_count} of ${rec.max_retries}`;
            }
          }
        }).catch(() => {});
      } else {
        alert(`Failed at ${stepLabel}: ${displayMsg}`);
        if (progressOverlay) progressOverlay.classList.add("d-none");
      }
      setActionButtonsProcessing(false);
    }

    const formData = new FormData(uploadForm);

    fetch("/api/analysis/start", {
      method: "POST",
      body: formData
    })
      .then(async (response) => {
        let data = {};
        try {
          data = await response.json();
        } catch (e) {
          data = {};
        }

        currentTaskId = data.task_id;
        currentAnalysisId = data.analysis_id;
        cancelUrl = data.cancel_url || `/api/analysis/cancel/${data.task_id}`;

        syncRateLimitFromHeaders(response, "analyze");

        if (response.status === 429 || (!response.ok && (data.retry_after || data.retry_after_seconds))) {
          handleRateLimitResponse(response, data, {
            scope: "analyze",
            submitButton: btnSubmitAnalysis,
            countdownElement: document.getElementById("analyzeCountdownTimer"),
            noticeContainer: document.getElementById("analyzeRateLimitNotice"),
            messageElement: document.getElementById("analyzeRateLimitMessage"),
          });
          const retryTime = formatCountdown(data.retry_after || data.retry_after_seconds || 60);
          const msg = data.message || `You have temporarily exceeded the request rate limit. You can try again in ${retryTime}.`;
          showPipelineError(msg, "Rate Limit");
          return;
        }

        if (!response.ok || !data.success) {
          throw new Error(data.error || "Failed to initiate background analysis.");
        }

        if (data.cached && data.redirect_url) {
          if (progressOverlay) progressOverlay.setAttribute("data-state", "success");
          if (analysisProgressBar) {
            analysisProgressBar.style.width = "100%";
            analysisProgressBar.className = "progress-bar bg-success";
          }
          if (progressSpinner) progressSpinner.classList.add("d-none");
          if (progressSuccessIcon) progressSuccessIcon.classList.remove("d-none");
          if (progressTitle) progressTitle.textContent = "Analysis Complete!";
          if (progressSubtitle) progressSubtitle.textContent = "Redirecting to your dashboard...";
          clearFormDraft();
          setTimeout(() => {
            window.location.href = data.redirect_url;
          }, 400);
          return;
        }

        const streamUrl = data.stream_url;
        const statusUrl = data.status_url;

        if (window.EventSource && streamUrl) {
          eventSource = new EventSource(streamUrl);

          eventSource.onmessage = (event) => {
            try {
              const milestone = JSON.parse(event.data);
              handleMilestone(milestone);
            } catch (jsonErr) {
              console.error("Failed to parse SSE JSON payload:", jsonErr);
            }
          };

          eventSource.onerror = (err) => {
            console.warn("EventSource disconnected; switching to polling fallback.", err);
            if (eventSource) {
              eventSource.close();
              eventSource = null;
            }
            startPolling(statusUrl, handleMilestone, showPipelineError);
          };
        } else {
          startPolling(statusUrl, handleMilestone, showPipelineError);
        }
      })
      .catch((err) => {
        console.error("Async analysis dispatch failed:", err);
        enableSubmitButton();
        showPipelineError(err.message || "Could not start analysis. Please check your network and retry.", "Dispatch");
      });
  });
}

// Auto-initialize when loaded on analysis pages
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initFormUpload();
      initCharacterCounters();
      initCircularProgress();
    });
  } else {
    initFormUpload();
    initCharacterCounters();
    initCircularProgress();
  }
}
