// Frontend interactions - AI Campus Placement Agent

document.addEventListener("DOMContentLoaded", () => {
  initThemeToggle();
  initFormUpload();
  initCircularProgress();
  initMockInterview();
  initCompanyExplorer();
  initSkillGapFilter();
  initRoadmapExport();
  initCodingSandbox();
});

function initThemeToggle() {
  const currentTheme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-bs-theme", currentTheme);

  const toggleBtns = document.querySelectorAll(".theme-toggle-btn");
  toggleBtns.forEach((btn) => {
    updateThemeIcon(btn, currentTheme);
    btn.addEventListener("click", () => {
      const activeTheme = document.documentElement.getAttribute("data-bs-theme");
      const newTheme = activeTheme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-bs-theme", newTheme);
      localStorage.setItem("theme", newTheme);
      toggleBtns.forEach((b) => updateThemeIcon(b, newTheme));
    });
  });
}

function updateThemeIcon(btn, theme) {
  if (theme === "dark") {
    btn.innerHTML = '<i class="fa-solid fa-sun text-warning"></i>';
    btn.title = "Switch to Light Mode";
  } else {
    btn.innerHTML = '<i class="fa-solid fa-moon text-secondary"></i>';
    btn.title = "Switch to Dark Mode";
  }
}

/**
 * Filter and search controls for the Skill Gap assessment table on the dashboard
 */
function initSkillGapFilter() {
  const searchInput = document.getElementById("skillSearchInput");
  const priorityFilter = document.getElementById("skillPriorityFilter");
  const table = document.getElementById("skillGapTable");
  const countBadge = document.getElementById("skillFilterCount");
  const emptyState = document.getElementById("skillGapEmptyState");

  if (!table || !searchInput || !priorityFilter) return;

  const rows = table.querySelectorAll("tbody tr.skill-gap-row");
  const totalRows = rows.length;

  function applyFilter() {
    const q = searchInput.value.toLowerCase().trim();
    const p = priorityFilter.value;
    let visibleCount = 0;

    rows.forEach((row) => {
      const skillName = (row.getAttribute("data-skill") || "").toLowerCase();
      const priority = (row.getAttribute("data-priority") || "").toLowerCase();
      const fullText = row.innerText.toLowerCase();

      const matchesSearch = !q || skillName.includes(q) || fullText.includes(q);
      const matchesPriority = p === "ALL" || priority === p.toLowerCase();

      if (matchesSearch && matchesPriority) {
        row.style.display = "";
        visibleCount++;
      } else {
        row.style.display = "none";
      }
    });

    if (emptyState) {
      if (visibleCount === 0 && totalRows > 0) {
        emptyState.classList.remove("d-none");
      } else {
        emptyState.classList.add("d-none");
      }
    }

    if (countBadge) {
      if (q || p !== "ALL") {
        countBadge.innerText = `Showing ${visibleCount} of ${totalRows} Skills`;
      } else {
        countBadge.innerText = `${totalRows} Skills`;
      }
    }
  }

  searchInput.addEventListener("input", applyFilter);
  priorityFilter.addEventListener("change", applyFilter);

  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && searchInput.value) {
      searchInput.value = "";
      applyFilter();
    }
  });
}

/**
 * Tracks interactive checklist tasks on the 6-Week Learning Roadmap
 * and persists completed task IDs in localStorage per analysis session.
 */
function initRoadmapTracker() {
  const container = document.getElementById("dashboardContainer");
  if (!container) return;

  const analysisId = container.getAttribute("data-analysis-id");
  if (!analysisId) return;

  const storageKey = `roadmap_tasks_${analysisId}`;
  let completedTasks = new Set();
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      completedTasks = new Set(JSON.parse(saved));
    }
  } catch (e) {
    console.warn("Could not load roadmap progress from localStorage:", e);
  }

  const allCheckboxes = document.querySelectorAll(".roadmap-task-check");
  const weekCards = document.querySelectorAll(".week-card");
  const overallLabel = document.getElementById("overallRoadmapProgressLabel");
  const overallBar = document.getElementById("overallRoadmapProgressBar");

  function updateVisuals() {
    let totalAll = allCheckboxes.length;
    let checkedAll = 0;

    weekCards.forEach((card) => {
      const checksInWeek = card.querySelectorAll(".roadmap-task-check");
      let checkedInWeek = 0;
      checksInWeek.forEach((cb) => {
        if (cb.checked) checkedInWeek++;
      });

      const pct = checksInWeek.length > 0 ? Math.round((checkedInWeek / checksInWeek.length) * 100) : 0;
      const bar = card.querySelector(".week-progress-bar");
      const label = card.querySelector(".week-progress-label");
      if (bar) bar.style.width = `${pct}%`;
      if (label) label.innerText = `${pct}%`;

      checkedAll += checkedInWeek;
    });

    const overallPct = totalAll > 0 ? Math.round((checkedAll / totalAll) * 100) : 0;
    if (overallLabel) overallLabel.innerText = `${overallPct}%`;
    if (overallBar) overallBar.style.width = `${overallPct}%`;
  }

  allCheckboxes.forEach((cb) => {
    const taskId = cb.getAttribute("data-task-id");
    if (taskId && completedTasks.has(taskId)) {
      cb.checked = true;
      const span = cb.parentElement?.querySelector("span");
      if (span) span.style.textDecoration = "line-through";
    }

    cb.addEventListener("change", () => {
      const span = cb.parentElement?.querySelector("span");
      if (cb.checked) {
        if (taskId) completedTasks.add(taskId);
        if (span) span.style.textDecoration = "line-through";
      } else {
        if (taskId) completedTasks.delete(taskId);
        if (span) span.style.textDecoration = "none";
      }

      try {
        localStorage.setItem(storageKey, JSON.stringify(Array.from(completedTasks)));
      } catch (e) {
        console.warn("Failed saving roadmap task progress to localStorage:", e);
      }

      updateVisuals();
    });
  });

  updateVisuals();
}

function initCompanyExplorer() {
  const btn = document.getElementById("btnExploreCompany");
  const select = document.getElementById("companySelect");
  const modalEl = document.getElementById("companyModal");
  const modalBody = document.getElementById("companyModalBody");
  if (!btn || !select || !modalEl) return;

  btn.addEventListener("click", async () => {
    const company = select.value;
    if (!company || company === "General") {
      alert("Please select a specific company (e.g. Google, Microsoft, Amazon) to explore its hiring guide.");
      return;
    }
    const bsModal = new bootstrap.Modal(modalEl);
    modalBody.innerHTML = '<div class="text-center py-4"><span class="spinner-border text-primary" role="status"></span></div>';
    bsModal.show();

    try {
      const res = await fetch(`/api/company/${encodeURIComponent(company)}`);
      const data = await res.json();
      if (data.success && data.details) {
        const d = data.details;
        modalBody.innerHTML = `
          <h4 class="fw-bold text-primary mb-3">${data.company}</h4>
          <p class="text-secondary">${d.overview || ""}</p>
          <hr/>
          <h6 class="fw-bold"><i class="fa-solid fa-list-check text-primary me-2"></i>Hiring Process:</h6>
          <p class="small text-muted mb-3">${d.hiring_process || "N/A"}</p>
          <h6 class="fw-bold"><i class="fa-solid fa-laptop-code text-primary me-2"></i>Technical Rounds:</h6>
          <p class="small text-muted mb-3">${d.technical_rounds || "N/A"}</p>
          <h6 class="fw-bold"><i class="fa-solid fa-lightbulb text-warning me-2"></i>Preparation Tips:</h6>
          <div class="alert alert-light border small text-dark">${d.prep_tips || "N/A"}</div>
        `;
      } else {
        modalBody.innerHTML = `<div class="alert alert-warning">No details found for ${company}.</div>`;
      }
    } catch (err) {
      modalBody.innerHTML = '<div class="alert alert-danger">Error loading company details.</div>';
    }
  });
}

/**
 * Handlers for landing page upload forms & progress panel animations
 */
function initFormUpload() {
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

  // Format file size nicely
  const formatFileSize = (bytes) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  // Helper to validate and display feedback for chosen resume file
  const handleSelectedFile = (file) => {
    if (!file) return;

    const fileName = file.name || "";
    const lowerName = fileName.toLowerCase();
    const isPdf = lowerName.endsWith(".pdf");
    const isDocx = lowerName.endsWith(".docx");

    // Hide any previous error
    if (uploadTypeErrorAlert) {
      uploadTypeErrorAlert.classList.add("d-none");
    }

    if (!isPdf && !isDocx) {
      // Show explicit unsupported error alert
      if (uploadTypeErrorAlert && uploadTypeErrorMessage) {
        uploadTypeErrorMessage.textContent = `Unsupported file type "${fileName.split('.').pop() || 'unknown'}". Only .pdf and .docx resume files are supported.`;
        uploadTypeErrorAlert.classList.remove("d-none");
      }
      uploadArea.classList.add("border-danger");
      uploadArea.style.backgroundColor = "#fff8f8";
      // Clear input
      if (fileInput) fileInput.value = "";
      if (fileFeedbackBadge) fileFeedbackBadge.classList.add("d-none");
      return false;
    }

    // Success styling and visual feedback badge
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

    return true;
  };

  // Helper to reset upload area to clean default state
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
  };

  // Highlight upload area on drag events and file change
  if (uploadArea && fileInput) {
    uploadArea.addEventListener("click", (e) => {
      // Don't trigger browse if clicking the remove button
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
        const file = fileInput.files[0];
        const lowerName = file.name.toLowerCase();
        const isDocx = lowerName.endsWith(".docx");
        const iconClass = isDocx ? "fa-file-word text-primary" : "fa-file-pdf text-danger";
        uploadArea.querySelector("p").innerHTML = `<i class="fa-solid ${iconClass} me-2"></i>Selected File: <b>${file.name}</b>`;
        uploadArea.style.borderColor = "var(--primary-blue)";
        uploadArea.style.backgroundColor = "var(--secondary-light)";
      }
    });

    ["dragenter", "dragover"].forEach(eventName => {
      uploadArea.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add("dragover-active");
        uploadArea.style.borderColor = "var(--primary-blue)";
        uploadArea.style.backgroundColor = "var(--secondary-light)";
      }, false);
    });

    ["dragleave"].forEach(eventName => {
      uploadArea.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove("dragover-active");
        if (fileInput.files.length === 0) {
          uploadArea.style.borderColor = "var(--border-color)";
          uploadArea.style.backgroundColor = "#ffffff";
        }
      }, false);
    });

    uploadArea.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      uploadArea.classList.remove("dragover-active");
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) {
        const file = files[0];
        const lowerName = file.name.toLowerCase();
        if (lowerName.endsWith(".pdf") || lowerName.endsWith(".docx")) {
          fileInput.files = files;
          const isDocx = lowerName.endsWith(".docx");
          const iconClass = isDocx ? "fa-file-word text-primary" : "fa-file-pdf text-danger";
          uploadArea.querySelector("p").innerHTML = `<i class="fa-solid ${iconClass} me-2"></i>Selected File: <b>${file.name}</b>`;
          uploadArea.style.borderColor = "var(--primary-blue)";
          uploadArea.style.backgroundColor = "var(--secondary-light)";
        }
      }
    });
  }

  const progressTitle = document.getElementById("progressTitle");
  const progressSubtitle = document.getElementById("progressSubtitle");
  const analysisProgressBar = document.getElementById("analysisProgressBar");
  const progressSpinner = document.getElementById("progressSpinner");
  const progressErrorAlert = document.getElementById("progressErrorAlert");
  const progressErrorMessage = document.getElementById("progressErrorMessage");
  const btnCloseProgressError = document.getElementById("btnCloseProgressError");

  if (btnCloseProgressError) {
    btnCloseProgressError.addEventListener("click", () => {
      if (progressOverlay) progressOverlay.classList.add("d-none");
      if (progressSpinner) progressSpinner.classList.remove("d-none");
      if (progressErrorAlert) progressErrorAlert.classList.add("d-none");
    });
  }

  const stepOrder = ["step1", "step2", "step3", "step4", "step5", "step6"];

  function resetProgressPanel() {
    if (progressSpinner) progressSpinner.classList.remove("d-none");
    if (progressErrorAlert) progressErrorAlert.classList.add("d-none");
    if (progressTitle) progressTitle.textContent = "Coordinating AI Agents";
    if (progressSubtitle) progressSubtitle.textContent = "Orchestrating multi-agent analysis in progress...";
    if (analysisProgressBar) {
      analysisProgressBar.style.width = "5%";
      analysisProgressBar.setAttribute("aria-valuenow", "5");
      analysisProgressBar.classList.add("progress-bar-animated");
    }

    stepOrder.forEach((stepId, idx) => {
      const el = document.getElementById(stepId);
      if (el) {
        el.className = "progress-step text-muted";
        const ind = el.querySelector(".step-indicator");
        if (ind) ind.textContent = String(idx + 1);
      }
    });
  }

  function startPolling(statusUrl, onMilestone, onError) {
    if (!statusUrl) return;
    let pollCount = 0;
    const maxPolls = 120; // 2 minutes max
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
            progress: 100,
            redirect_url: statusData.redirect_url,
            message: "Multi-agent placement analysis complete! Redirecting..."
          });
        } else if (statusData.status === "error") {
          clearInterval(pollInterval);
          onError(statusData.error_message || "Analysis pipeline encountered an error.");
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

  // Intercept form submit to launch async pipeline & stream milestones via EventSource
  uploadForm.addEventListener("submit", (e) => {
    e.preventDefault();

    const textInput = document.getElementById("resumeTextInput");
    const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
    const hasText = textInput && textInput.value.trim().length > 0;

    if (!hasFile && !hasText) {
      alert("Please upload a PDF or DOCX resume, or paste your resume text first.");
      return;
    }

    // Display and reset progress overlay
    resetProgressPanel();
    if (progressOverlay) progressOverlay.classList.remove("d-none");

    let eventSource = null;

    function handleMilestone(milestone) {
      const step = milestone.step;
      const progress = milestone.progress || 0;
      const message = milestone.message || "";
      const status = milestone.status;

      if (analysisProgressBar) {
        analysisProgressBar.style.width = `${progress}%`;
        analysisProgressBar.setAttribute("aria-valuenow", String(progress));
      }

      if (progressSubtitle && message) {
        progressSubtitle.textContent = message;
      }

      if (step && step.startsWith("step")) {
        const currentIdx = stepOrder.indexOf(step);
        stepOrder.forEach((sId, idx) => {
          const el = document.getElementById(sId);
          if (!el) return;
          const ind = el.querySelector(".step-indicator");
          if (idx < currentIdx) {
            el.className = "progress-step completed";
            if (ind) ind.innerHTML = "✓";
          } else if (idx === currentIdx) {
            el.className = "progress-step active";
          } else {
            el.className = "progress-step text-muted";
          }
        });
      }

      if (status === "completed" || step === "completed") {
        stepOrder.forEach((sId) => {
          const el = document.getElementById(sId);
          if (el) {
            el.className = "progress-step completed";
            const ind = el.querySelector(".step-indicator");
            if (ind) ind.innerHTML = "✓";
          }
        });

        if (analysisProgressBar) {
          analysisProgressBar.style.width = "100%";
          analysisProgressBar.classList.remove("progress-bar-animated");
        }
        if (progressTitle) progressTitle.textContent = "Analysis Complete!";
        if (progressSubtitle) progressSubtitle.textContent = "Redirecting to your comprehensive placement dashboard...";

        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }

        const redirectUrl = milestone.redirect_url ||
          (milestone.extra && milestone.extra.redirect_url) ||
          "/";
        setTimeout(() => {
          window.location.href = redirectUrl;
        }, 500);
      } else if (status === "error" || step === "error") {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        showPipelineError(milestone.message || "An unexpected error occurred during multi-agent analysis.");
      }
    }

    function showPipelineError(errMsg) {
      if (progressSpinner) progressSpinner.classList.add("d-none");
      if (progressErrorAlert && progressErrorMessage) {
        progressErrorMessage.textContent = errMsg;
        progressErrorAlert.classList.remove("d-none");
      } else {
        alert(errMsg);
        if (progressOverlay) progressOverlay.classList.add("d-none");
      }
    }

    const formData = new FormData(uploadForm);

    fetch("/api/analysis/start", {
      method: "POST",
      body: formData
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.error || "Failed to initiate background analysis.");
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
        showPipelineError(err.message || "Could not start analysis. Please check your network and retry.");
      });
  });
}

/**
 * Renders the circular SVG progress dials
 */
function initCircularProgress() {
  const circles = document.querySelectorAll(".circular-fill-ring");
  circles.forEach(circle => {
    const score = circle.getAttribute("data-score");
    if (score) {
      const radius = circle.r.baseVal.value;
      const circumference = 2 * Math.PI * radius;
      const offset = circumference - (score / 100) * circumference;
      
      // Animate circular transition
      setTimeout(() => {
        circle.style.strokeDasharray = `${circumference} ${circumference}`;
        circle.style.strokeDashoffset = offset;
      }, 300);
    }
  });
}

/**
 * Manages the live interactive mock interview simulation
 */
/**
 * Manages the live interactive mock interview simulation with Voice-Enabled AI Interviewer:
 * - Real-time Web Speech API recognition (Speech-to-Text) with continuous interim transcription
 * - Audio visualizer wave animation and recording timer
 * - Pre-submission editable transcript review
 * - Speech Synthesis (Text-to-Speech) for interviewer questions with auto-speak toggle
 * - Dynamic verbal indicators evaluation (Verbal clarity, filler words, STAR method)
 */
function initMockInterview() {
  const chatForm = document.getElementById("chatForm");
  if (!chatForm) return;

  const chatContainer = document.getElementById("chatContainer");
  const answerInput = document.getElementById("answerInput");
  const submitBtn = chatForm.querySelector("button[type='submit']");
  const evaluationPanel = document.getElementById("evaluationPanel");
  const btnMic = document.getElementById("btnMic");
  const voiceRecordingPanel = document.getElementById("voiceRecordingPanel");
  const btnStopVoice = document.getElementById("btnStopVoice");
  const btnClearTranscript = document.getElementById("btnClearTranscript");
  const btnAppendTranscript = document.getElementById("btnAppendTranscript");
  const liveInterimText = document.getElementById("liveInterimText");
  const recordingStatusText = document.getElementById("recordingStatusText");
  const voiceWaveform = document.getElementById("voiceWaveform");
  const speechTimerBadge = document.getElementById("speechTimerBadge");
  const transcriptWordCount = document.getElementById("transcriptWordCount");
  const toggleAutoTTS = document.getElementById("toggleAutoTTS");

  // State trackers
  let recognition = null;
  let isRecording = false;
  let speechTimerInterval = null;
  let speechSeconds = 0;
  let activeUtteranceBtn = null;

  // -------------------------------------------------------------
  // 1. Text-to-Speech (TTS) Speech Synthesis Integration
  // -------------------------------------------------------------
  const isSpeechSynthesisSupported = "speechSynthesis" in window;

  // Restore Auto-Speak toggle preference from localStorage
  if (toggleAutoTTS) {
    const savedAutoTTS = localStorage.getItem("ai_interview_auto_tts");
    if (savedAutoTTS !== null) {
      toggleAutoTTS.checked = savedAutoTTS === "true";
    }
    toggleAutoTTS.addEventListener("change", () => {
      localStorage.setItem("ai_interview_auto_tts", toggleAutoTTS.checked);
      if (!toggleAutoTTS.checked && isSpeechSynthesisSupported) {
        window.speechSynthesis.cancel();
        resetSpeakingButtons();
      }
    });
  }

  function resetSpeakingButtons() {
    document.querySelectorAll(".btn-tts.speaking").forEach((btn) => {
      btn.classList.remove("speaking");
      btn.innerHTML = '<i class="fa-solid fa-volume-high me-1"></i> Listen';
    });
    activeUtteranceBtn = null;
  }

  function speakQuestionText(text, btnElement = null) {
    if (!isSpeechSynthesisSupported || !text) return;

    // Toggle stop if already speaking this button
    if (btnElement && btnElement.classList.contains("speaking")) {
      window.speechSynthesis.cancel();
      resetSpeakingButtons();
      return;
    }

    window.speechSynthesis.cancel();
    resetSpeakingButtons();

    // Clean plain text without markdown or HTML tags
    const cleanText = text.replace(/<[^>]*>?/gm, "").replace(/\[\s*Question[^\]]+\]/gi, "").trim();
    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 0.95;
    utterance.pitch = 1.0;

    // Choose preferred English voice if available
    const voices = window.speechSynthesis.getVoices();
    const englishVoice = voices.find((v) => v.lang.startsWith("en") && (v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Online")));
    if (englishVoice) {
      utterance.voice = englishVoice;
    }

    if (btnElement) {
      activeUtteranceBtn = btnElement;
      btnElement.classList.add("speaking");
      btnElement.innerHTML = '<i class="fa-solid fa-volume-xmark me-1"></i> Stop';
    }

    utterance.onend = () => {
      resetSpeakingButtons();
    };

    utterance.onerror = () => {
      resetSpeakingButtons();
    };

    window.speechSynthesis.speak(utterance);
  }

  // Delegated click listener for all TTS buttons (initial & dynamically added)
  if (chatContainer) {
    chatContainer.addEventListener("click", (e) => {
      const ttsBtn = e.target.closest(".btn-tts");
      if (ttsBtn) {
        e.preventDefault();
        const textToSpeak = ttsBtn.getAttribute("data-tts") || ttsBtn.closest(".chat-bubble-agent")?.innerText || "";
        speakQuestionText(textToSpeak, ttsBtn);
      }
    });
  }

  // Auto-speak initial active question if toggle is checked
  if (toggleAutoTTS && toggleAutoTTS.checked) {
    setTimeout(() => {
      const currentQBubble = document.getElementById("currentQuestionBubble");
      if (currentQBubble) {
        const initialTtsBtn = currentQBubble.querySelector(".btn-tts");
        const currentQText = document.getElementById("currentQuestionText")?.innerText || "";
        speakQuestionText(currentQText, initialTtsBtn);
      }
    }, 600);
  }

  // -------------------------------------------------------------
  // 2. Web Speech API (Speech-to-Text) & Audio Visualizer
  // -------------------------------------------------------------
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let finalTranscript = "";

    function updateSpeechTimer() {
      speechSeconds++;
      const mins = String(Math.floor(speechSeconds / 60)).padStart(2, "0");
      const secs = String(speechSeconds % 60).padStart(2, "0");
      if (speechTimerBadge) {
        speechTimerBadge.innerHTML = `<i class="fa-regular fa-clock me-1"></i>${mins}:${secs}`;
      }
    }

    function updateTranscriptWordCount(text) {
      if (!transcriptWordCount) return;
      const count = text.trim() ? text.trim().split(/\s+/).filter(Boolean).length : 0;
      transcriptWordCount.innerText = `${count} word${count === 1 ? "" : "s"} captured`;
    }

    function startVoiceRecording() {
      try {
        finalTranscript = liveInterimText ? liveInterimText.innerText.trim() : "";
        recognition.start();
        isRecording = true;
        speechSeconds = 0;
        if (speechTimerBadge) speechTimerBadge.innerHTML = '<i class="fa-regular fa-clock me-1"></i>00:00';
        clearInterval(speechTimerInterval);
        speechTimerInterval = setInterval(updateSpeechTimer, 1000);

        if (voiceRecordingPanel) voiceRecordingPanel.classList.remove("d-none");
        if (voiceWaveform) voiceWaveform.classList.add("active");
        if (recordingStatusText) {
          recordingStatusText.innerText = "Listening... Speak clearly into your microphone";
          recordingStatusText.className = "small fw-bold text-danger";
        }
        if (btnMic) {
          btnMic.classList.remove("btn-outline-primary");
          btnMic.classList.add("btn-danger");
          btnMic.innerHTML = '<i class="fa-solid fa-microphone-slash me-1"></i> Stop Voice';
        }
      } catch (err) {
        console.warn("Speech recognition already running or permission issue:", err);
      }
    }

    function stopVoiceRecording() {
      if (!isRecording) return;
      isRecording = false;
      try {
        recognition.stop();
      } catch (e) {
        // Safe ignore
      }
      clearInterval(speechTimerInterval);
      if (voiceWaveform) voiceWaveform.classList.remove("active");
      if (recordingStatusText) {
        recordingStatusText.innerText = "Recording paused. Review or insert your answer below.";
        recordingStatusText.className = "small fw-bold text-success";
      }
      if (btnMic) {
        btnMic.classList.remove("btn-danger");
        btnMic.classList.add("btn-outline-primary");
        btnMic.innerHTML = '<i class="fa-solid fa-microphone"></i> <span class="d-none d-sm-inline small fw-semibold">Voice Answer</span>';
      }
    }

    if (btnMic) {
      btnMic.addEventListener("click", () => {
        if (!isRecording) {
          startVoiceRecording();
        } else {
          stopVoiceRecording();
        }
      });
    }

    if (btnStopVoice) {
      btnStopVoice.addEventListener("click", () => {
        stopVoiceRecording();
      });
    }

    recognition.onresult = (event) => {
      let interimTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += " " + event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }

      const fullCapturedText = (finalTranscript + " " + interimTranscript).trim();
      if (liveInterimText) {
        liveInterimText.innerText = fullCapturedText;
        updateTranscriptWordCount(fullCapturedText);
      }
    };

    recognition.onerror = (event) => {
      console.warn("Speech recognition error:", event.error);
      if (recordingStatusText) {
        recordingStatusText.innerText = `Microphone notice: ${event.error}. Click Voice Answer to retry.`;
        recordingStatusText.className = "small fw-semibold text-warning";
      }
      stopVoiceRecording();
    };

    recognition.onend = () => {
      if (isRecording) {
        // Auto-restart if continuous dictation stopped unexpectedly
        try {
          recognition.start();
        } catch (e) {
          stopVoiceRecording();
        }
      } else {
        stopVoiceRecording();
      }
    };

    // Pre-submission review actions
    if (btnClearTranscript && liveInterimText) {
      btnClearTranscript.addEventListener("click", () => {
        liveInterimText.innerText = "";
        finalTranscript = "";
        updateTranscriptWordCount("");
      });
    }

    if (btnAppendTranscript && liveInterimText && answerInput) {
      btnAppendTranscript.addEventListener("click", () => {
        const textToInsert = liveInterimText.innerText.trim();
        if (textToInsert) {
          const currentVal = answerInput.value.trim();
          answerInput.value = currentVal ? `${currentVal} ${textToInsert}` : textToInsert;
          triggerWordCounter(answerInput);
          liveInterimText.innerText = "";
          finalTranscript = "";
          updateTranscriptWordCount("");
          stopVoiceRecording();
          answerInput.focus();
        }
      });
    }

    if (liveInterimText) {
      liveInterimText.addEventListener("input", () => {
        finalTranscript = liveInterimText.innerText.trim();
        updateTranscriptWordCount(finalTranscript);
      });
    }

  } else {
    // Web Speech API not supported in browser
    if (btnMic) {
      btnMic.title = "Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.";
      btnMic.style.opacity = "0.7";
      btnMic.addEventListener("click", () => {
        alert("Speech Recognition is not supported by your browser. Please use Google Chrome, Microsoft Edge, or Safari for voice answering.");
      });
    }
  }

  // -------------------------------------------------------------
  // 3. Live Word Counter & Keyboard Shortcuts
  // -------------------------------------------------------------
  function triggerWordCounter(inputEl) {
    const wordCountBadge = document.getElementById("wordCountBadge");
    if (!wordCountBadge || !inputEl) return;
    const text = inputEl.value.trim();
    const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
    wordCountBadge.innerText = `${words} word${words === 1 ? "" : "s"}`;
    if (words >= 30) {
      wordCountBadge.className = "text-success fw-bold";
    } else {
      wordCountBadge.className = "text-secondary fw-semibold";
    }
  }

  if (answerInput) {
    answerInput.addEventListener("input", () => {
      triggerWordCounter(answerInput);
    });

    answerInput.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        chatForm.requestSubmit();
      }
    });
  }

  // -------------------------------------------------------------
  // 4. Form Submission & Agent Evaluation Pipeline
  // -------------------------------------------------------------
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const answer = answerInput.value ? answerInput.value.trim() : "";
    if (!answer) {
      alert("Please enter or voice-record a response before submitting.");
      return;
    }

    // Stop active speech recognition or TTS
    if (recognition && isRecording) {
      try { recognition.stop(); } catch (err) {}
      isRecording = false;
    }
    if (isSpeechSynthesisSupported) {
      window.speechSynthesis.cancel();
      resetSpeakingButtons();
    }

    const questionIndex = parseInt(chatForm.getAttribute("data-question-index"));
    const analysisId = chatForm.getAttribute("data-analysis-id");

    // Disable inputs during evaluation
    answerInput.disabled = true;
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status"></span>`;

    // Append user answer bubble
    appendChatBubble(answer, "user");
    answerInput.value = "";
    triggerWordCounter(answerInput);

    // Append loader bubble from Interview Agent
    const loaderBubble = appendChatBubble("<i>Interview Agent is evaluating your response and verbal delivery...</i>", "agent");

    try {
      const response = await fetch(`/interview/${analysisId}/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          answer: answer,
          question_index: questionIndex
        })
      });

      const result = await response.json();
      loaderBubble.remove();

      if (result.error) {
        appendChatBubble(`Error: ${result.error}`, "agent");
        resetInputs();
        return;
      }

      // Display dynamic feedback scores on dashboard panels
      renderEvaluationDetails(result.evaluation, questionIndex + 1);

      // Construct rich feedback bubble with verbal metrics
      const evalData = result.evaluation;
      const verbalClarity = evalData.verbal_clarity_score || evalData.communication_score || 50;
      let fillersHtml = "";
      if (evalData.filler_words_detected && evalData.filler_words_detected.length > 0) {
        fillersHtml = `
          <div class="small mb-1 text-muted">
            <i class="fa-solid fa-microphone-lines text-warning me-1"></i> <b>Fillers detected (${evalData.filler_word_count || evalData.filler_words_detected.length}):</b>
            ${evalData.filler_words_detected.map(fw => `<span class="badge bg-warning-subtle text-dark border border-warning-subtle rounded-pill me-1">${fw}</span>`).join("")}
          </div>
        `;
      }

      let starHtml = "";
      if (evalData.star_method_analysis && evalData.star_method_analysis.feedback) {
        starHtml = `
          <div class="small mb-2 text-secondary">
            <i class="fa-solid fa-sitemap text-primary me-1"></i> <b>STAR Framework:</b> ${evalData.star_method_analysis.feedback}
          </div>
        `;
      }

      const feedbackText = `
        <b>Feedback:</b> ${evalData.feedback}<br/>
        <div class="row g-2 mt-2 mb-2">
          <div class="col-sm-4"><span class="badge bg-primary-subtle text-primary border border-primary-subtle w-100 py-1">Tech: ${evalData.technical_accuracy}/100</span></div>
          <div class="col-sm-4"><span class="badge bg-success-subtle text-success border border-success-subtle w-100 py-1">Comm: ${evalData.communication_score}/100</span></div>
          <div class="col-sm-4"><span class="badge bg-info-subtle text-info border border-info-subtle w-100 py-1">Verbal Clarity: ${verbalClarity}/100</span></div>
        </div>
        ${fillersHtml}
        ${starHtml}
        <b>Suggestions:</b><br/>
        <ul class="mb-0 mt-1">
          ${(evalData.suggestions || []).map(s => `<li>${s}</li>`).join("")}
        </ul>
      `;
      appendChatBubble(feedbackText, "agent");

      if (result.completed) {
        appendChatBubble("<b>Congratulations! You have completed all mock interview questions.</b><br/>Please review your performance summary and export your transcript.", "agent");
        resetInputs(true);
        document.getElementById("btnBackToDashboard")?.classList.remove("btn-outline-secondary");
        document.getElementById("btnBackToDashboard")?.classList.add("btn-primary");

        if (result.summary) {
          showCompletionModal(result.summary);
        }
      } else {
        // Move to next question with TTS vocalization
        const nextQ = result.next_question;
        setTimeout(() => {
          const nextBubbleHtml = `
            <div class="d-flex justify-content-between align-items-start mb-1">
              <span>[<b>Question ${nextQ.index + 1} - ${nextQ.type}</b>]</span>
              <button type="button" class="btn btn-sm btn-outline-primary btn-tts py-0 px-2 rounded-pill" title="Read question aloud" data-tts="${nextQ.question.replace(/"/g, '&quot;')}">
                <i class="fa-solid fa-volume-high me-1"></i> Listen
              </button>
            </div>
            <div>${nextQ.question}</div>
          `;
          const newBubble = appendChatBubble(nextBubbleHtml, "agent");
          chatForm.setAttribute("data-question-index", nextQ.index);
          resetInputs();

          // Auto-read question aloud if toggle is checked
          if (toggleAutoTTS && toggleAutoTTS.checked) {
            const newTtsBtn = newBubble.querySelector(".btn-tts");
            speakQuestionText(nextQ.question, newTtsBtn);
          }
        }, 1000);
      }

    } catch (err) {
      loaderBubble.remove();
      appendChatBubble("Could not evaluate response. Check your network connection or API configs.", "agent");
      resetInputs();
    }
  });

  function appendChatBubble(text, sender) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble-${sender} fade-in`;
    bubble.innerHTML = text;
    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return bubble;
  }

  function resetInputs(disableAll = false) {
    answerInput.disabled = disableAll;
    submitBtn.disabled = disableAll;
    submitBtn.innerHTML = "Submit Answer";
  }

  function renderEvaluationDetails(evaluation, totalAnswered) {
    if (evaluationPanel) {
      evaluationPanel.classList.remove("d-none");
    }

    // Gauges
    const conf = evaluation.confidence_score || 0;
    const comm = evaluation.communication_score || 0;
    const tech = evaluation.technical_accuracy || 0;
    const verbal = evaluation.verbal_clarity_score || comm || 0;

    const confScoreEl = document.getElementById("confScore");
    const confBarEl = document.getElementById("confBar");
    if (confScoreEl) confScoreEl.innerText = `${conf}%`;
    if (confBarEl) confBarEl.style.width = `${conf}%`;

    const commScoreEl = document.getElementById("commScore");
    const commBarEl = document.getElementById("commBar");
    if (commScoreEl) commScoreEl.innerText = `${comm}%`;
    if (commBarEl) commBarEl.style.width = `${comm}%`;

    const techScoreEl = document.getElementById("techScore");
    const techBarEl = document.getElementById("techBar");
    if (techScoreEl) techScoreEl.innerText = `${tech}%`;
    if (techBarEl) techBarEl.style.width = `${tech}%`;

    const verbalScoreEl = document.getElementById("verbalScore");
    const verbalBarEl = document.getElementById("verbalBar");
    if (verbalScoreEl) verbalScoreEl.innerText = `${verbal}%`;
    if (verbalBarEl) verbalBarEl.style.width = `${verbal}%`;

    // Verbal indicators card
    const fillerWordsText = document.getElementById("fillerWordsText");
    if (fillerWordsText) {
      if (evaluation.filler_words_detected && evaluation.filler_words_detected.length > 0) {
        fillerWordsText.innerText = `${evaluation.filler_word_count || evaluation.filler_words_detected.length} (${evaluation.filler_words_detected.join(", ")})`;
      } else {
        fillerWordsText.innerText = "None detected (Clean pacing)";
      }
    }

    const starStructureText = document.getElementById("starStructureText");
    if (starStructureText) {
      starStructureText.innerText = evaluation.star_method_analysis?.feedback || "Structured response recorded";
    }

    // Progress updates
    const totalQuestions = parseInt(chatForm.getAttribute("data-total-questions")) || 15;
    const progPercent = totalQuestions > 0 ? Math.round((totalAnswered / totalQuestions) * 100) : 0;
    const progressTextEl = document.getElementById("interviewProgressText");
    const progressBarEl = document.getElementById("interviewProgressBar");
    if (progressTextEl) progressTextEl.innerText = `${totalAnswered}/${totalQuestions} Questions Answered (${progPercent}%)`;
    if (progressBarEl) progressBarEl.style.width = `${progPercent}%`;
  }

  function showCompletionModal(summary) {
    const modalEl = document.getElementById("completionModal");
    if (!modalEl || typeof bootstrap === "undefined") return;

    const overallScoreEl = document.getElementById("modalOverallScore");
    const verdictBadge = document.getElementById("modalVerdictBadge");
    const feedbackEl = document.getElementById("modalSummaryFeedback");
    const hrScoreEl = document.getElementById("modalHrScore");
    const techScoreEl = document.getElementById("modalTechScore");
    const behScoreEl = document.getElementById("modalBehScore");

    if (overallScoreEl) overallScoreEl.innerText = summary.overall_score || "0";
    if (verdictBadge) verdictBadge.innerText = summary.readiness_verdict || "Completed";
    if (feedbackEl && summary.summary_feedback) feedbackEl.innerText = summary.summary_feedback;

    const cats = summary.category_scores || {};
    if (hrScoreEl && cats.HR) hrScoreEl.innerText = `${cats.HR.average_score}%`;
    if (techScoreEl && cats.Technical) techScoreEl.innerText = `${cats.Technical.average_score}%`;
    if (behScoreEl && cats.Behavioral) behScoreEl.innerText = `${cats.Behavioral.average_score}%`;

    // Also populate inline completed scorecard if present
    const scorecardTech = document.getElementById("scorecardTechScore");
    const scorecardComm = document.getElementById("scorecardCommScore");
    const scorecardClarity = document.getElementById("scorecardClarityScore");
    const barTech = document.getElementById("progressBarTech");
    const barComm = document.getElementById("progressBarComm");
    const barClarity = document.getElementById("progressBarClarity");

    const tScore = cats.Technical ? Math.round(cats.Technical.average_score) : Math.round(summary.overall_score || 0);
    const cScore = cats.HR ? Math.round(cats.HR.average_score) : Math.round(summary.overall_score || 0);
    const clarScore = summary.verbal_metrics ? Math.round(summary.verbal_metrics.average_verbal_clarity || 0) : cScore;

    if (scorecardTech) scorecardTech.innerText = `${tScore}%`;
    if (barTech) barTech.style.width = `${tScore}%`;
    if (scorecardComm) scorecardComm.innerText = `${cScore}%`;
    if (barComm) barComm.style.width = `${cScore}%`;
    if (scorecardClarity) scorecardClarity.innerText = `${clarScore}%`;
    if (barClarity) barClarity.style.width = `${clarScore}%`;

    // Display Verbal Performance Metrics in Modal if available
    const modalVerbalStatsCard = document.getElementById("modalVerbalStatsCard");
    const modalVerbalClarity = document.getElementById("modalVerbalClarity");
    const modalTotalFillers = document.getElementById("modalTotalFillers");
    const modalStarRate = document.getElementById("modalStarRate");

    if (summary.verbal_metrics && modalVerbalStatsCard) {
      modalVerbalStatsCard.classList.remove("d-none");
      if (modalVerbalClarity) modalVerbalClarity.innerText = `${summary.verbal_metrics.average_verbal_clarity}%`;
      if (modalTotalFillers) modalTotalFillers.innerText = `${summary.verbal_metrics.total_filler_words}`;
      if (modalStarRate) modalStarRate.innerText = `${summary.verbal_metrics.star_adherence_rate}`;
    }

    const bsModal = new bootstrap.Modal(modalEl);
    bsModal.show();
  }
}

/**
 * Enables copying single-week roadmap tasks and exporting the complete 6-week
 * preparation schedule as a structured Markdown file for study notes or Notion.
 */
function initRoadmapExport() {
  const container = document.getElementById("dashboardContainer");
  if (!container) return;

  const companyName = container.getAttribute("data-company") || "Placement Target";

  // 1. Copy individual week tasks
  document.querySelectorAll(".copy-week-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const card = btn.closest(".week-card");
      if (!card) return;

      const weekTitle = btn.getAttribute("data-week-name") || "Week";
      const hours = card.querySelector(".badge")?.innerText || "";
      let md = `### ${weekTitle} (${hours})\n\n`;

      const appendSection = (heading, selector) => {
        const items = card.querySelectorAll(selector);
        if (items.length > 0) {
          md += `#### ${heading}:\n`;
          items.forEach((item) => {
            const text = item.innerText.trim();
            if (text) md += `- [ ] ${text}\n`;
          });
          md += "\n";
        }
      };

      appendSection("Topics to Learn", ".roadmap-task-check[data-task-id*='_top_'] + span");
      appendSection("Coding Practice", ".roadmap-task-check[data-task-id*='_code_'] + span");
      appendSection("Micro Projects", ".roadmap-task-check[data-task-id*='_proj_'] + span");
      appendSection("Interview Prep Questions", ".roadmap-task-check[data-task-id*='_q_'] + span");

      const rev = card.querySelector(".border-top p")?.innerText.trim();
      if (rev) {
        md += `#### Revision Tasks:\n${rev}\n\n`;
      }

      try {
        await navigator.clipboard.writeText(md);
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check text-success me-1"></i> Copied!';
        btn.classList.add("btn-success-subtle");
        setTimeout(() => {
          btn.innerHTML = originalHtml;
          btn.classList.remove("btn-success-subtle");
        }, 2000);
      } catch (err) {
        console.warn("Clipboard copy failed, fallback prompted:", err);
      }
    });
  });

  // 2. Export full 6-week study plan as a Markdown file
  const exportBtn = document.getElementById("btnExportRoadmapMarkdown");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      let fullMd = `# 6-Week Placement Preparation Roadmap\n`;
      fullMd += `**Target Company:** ${companyName}\n`;
      fullMd += `**Generated by:** AI Campus Placement Agent\n\n`;
      fullMd += `---\n\n`;

      document.querySelectorAll(".week-card").forEach((card) => {
        const title = card.querySelector("h5")?.innerText.trim() || "Week";
        const hours = card.querySelector(".badge")?.innerText.trim() || "";
        fullMd += `## ${title} (${hours})\n\n`;

        const appendSection = (heading, selector) => {
          const items = card.querySelectorAll(selector);
          if (items.length > 0) {
            fullMd += `### ${heading}:\n`;
            items.forEach((item) => {
              const text = item.innerText.trim();
              if (text) fullMd += `- [ ] ${text}\n`;
            });
            fullMd += "\n";
          }
        };

        appendSection("Topics to Learn", ".roadmap-task-check[data-task-id*='_top_'] + span");
        appendSection("Coding Practice Tasks", ".roadmap-task-check[data-task-id*='_code_'] + span");
        appendSection("Micro Projects", ".roadmap-task-check[data-task-id*='_proj_'] + span");
        appendSection("Interview Prep Questions", ".roadmap-task-check[data-task-id*='_q_'] + span");

        const rev = card.querySelector(".border-top p")?.innerText.trim();
        if (rev) {
          fullMd += `### Revision Tasks:\n${rev}\n\n`;
        }
        fullMd += `---\n\n`;
      });

      const blob = new Blob([fullMd], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Study_Plan_${companyName.replace(/[^a-zA-Z0-9_-]/g, "_")}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }
}

/**
 * Multi-Version Resume Comparison & Longitudinal Progress Tracker
 * - Initializes Chart.js line/area chart showing ATS Score, Job Match %, and Skill Gaps over time
 * - Supports theme-reactive colors for gridlines and text
 * - Manages interactive side-by-side diff modal and dynamic baseline selection
 */
function initProgressTracker() {
  const trackerCard = document.getElementById("progressTrackerCard");
  if (!trackerCard) return;

  const trendRaw = trackerCard.getAttribute("data-trend");
  let trendData = null;
  try {
    trendData = trendRaw ? JSON.parse(trendRaw) : null;
  } catch (err) {
    console.warn("Could not parse trend data for Chart.js:", err);
  }

  // 1. Initialize Chart.js longitudinal trend chart
  const canvas = document.getElementById("progressTrendChart");
  if (canvas && window.Chart && trendData && Array.isArray(trendData.labels) && trendData.labels.length > 0) {
    const isDark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    const textColor = isDark ? "#c4c7c5" : "#444746";
    const gridColor = isDark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.06)";

    const ctx = canvas.getContext("2d");
    const progressChart = new window.Chart(ctx, {
      type: "line",
      data: {
        labels: trendData.labels,
        datasets: [
          {
            label: "ATS Profile Score",
            data: trendData.ats_scores,
            borderColor: "#1a73e8",
            backgroundColor: "rgba(26, 115, 232, 0.12)",
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 5,
            pointHoverRadius: 7,
            pointBackgroundColor: "#1a73e8",
            yAxisID: "y"
          },
          {
            label: "Job Match %",
            data: trendData.match_scores,
            borderColor: "#34a853",
            backgroundColor: "rgba(52, 168, 83, 0.08)",
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 5,
            pointHoverRadius: 7,
            pointBackgroundColor: "#34a853",
            yAxisID: "y"
          },
          {
            label: "Skill Gaps Count",
            data: trendData.gap_counts,
            borderColor: "#ea4335",
            borderDash: [5, 5],
            backgroundColor: "transparent",
            fill: false,
            tension: 0.3,
            borderWidth: 2,
            pointRadius: 4,
            pointBackgroundColor: "#ea4335",
            yAxisID: "y1"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false
        },
        plugins: {
          legend: {
            position: "top",
            labels: {
              boxWidth: 14,
              font: { size: 12, family: "'Outfit', sans-serif" },
              color: textColor
            }
          },
          tooltip: {
            backgroundColor: isDark ? "#282a2c" : "#ffffff",
            titleColor: isDark ? "#e3e3e3" : "#1f1f1f",
            bodyColor: isDark ? "#c4c7c5" : "#444746",
            borderColor: isDark ? "#444746" : "#dadce0",
            borderWidth: 1,
            padding: 10,
            callbacks: {
              title: function (items) {
                const idx = items[0].dataIndex;
                const date = trendData.dates && trendData.dates[idx] ? trendData.dates[idx] : "";
                const filename = trendData.filenames && trendData.filenames[idx] ? trendData.filenames[idx] : "";
                return `Iteration ${trendData.labels[idx]} (${date}) - ${filename}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: gridColor },
            ticks: { color: textColor, font: { family: "'Outfit', sans-serif" } }
          },
          y: {
            type: "linear",
            display: true,
            position: "left",
            min: 0,
            max: 100,
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              callback: val => `${val}%`,
              font: { family: "'Outfit', sans-serif" }
            }
          },
          y1: {
            type: "linear",
            display: true,
            position: "right",
            min: 0,
            suggestedMax: 8,
            grid: { drawOnChartArea: false },
            ticks: {
              color: "#ea4335",
              precision: 0,
              font: { family: "'Outfit', sans-serif" }
            }
          }
        }
      }
    });

    // Theme toggle listener to update chart colors
    const observer = new MutationObserver(() => {
      const darkNow = document.documentElement.getAttribute("data-bs-theme") === "dark";
      const newTextColor = darkNow ? "#c4c7c5" : "#444746";
      const newGridColor = darkNow ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.06)";

      if (progressChart) {
        progressChart.options.scales.x.ticks.color = newTextColor;
        progressChart.options.scales.x.grid.color = newGridColor;
        progressChart.options.scales.y.ticks.color = newTextColor;
        progressChart.options.scales.y.grid.color = newGridColor;
        progressChart.options.plugins.legend.labels.color = newTextColor;
        progressChart.update();
      }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
  }

  // 2. Interactive side-by-side diff modal dropdown switcher
  const diffModal = document.getElementById("versionDiffModal");
  const selectBaseline = document.getElementById("selectDiffBaseline");
  const diffLoadingSpinner = document.getElementById("diffLoadingSpinner");
  const diffContentArea = document.getElementById("diffContentArea");

  if (diffModal && selectBaseline) {
    const currentAnalysisId = diffModal.getAttribute("data-current-id");

    selectBaseline.addEventListener("change", async () => {
      const baselineId = selectBaseline.value;
      if (!baselineId || !currentAnalysisId) return;

      if (diffLoadingSpinner) diffLoadingSpinner.classList.remove("d-none");
      if (diffContentArea) diffContentArea.classList.add("opacity-25");

      try {
        const response = await fetch(`/api/progress/diff/${baselineId}/${currentAnalysisId}`);
        const data = await response.json();

        if (data.status === "success" && data.diff) {
          renderDiffModalContent(data.diff);
        }
      } catch (err) {
        console.error("Failed to fetch version diff comparison:", err);
      } finally {
        if (diffLoadingSpinner) diffLoadingSpinner.classList.add("d-none");
        if (diffContentArea) diffContentArea.classList.remove("opacity-25");
      }
    });
  }

  function renderDiffModalContent(diff) {
    const a = diff.version_a || {};
    const b = diff.version_b || {};
    const d = diff.delta || {};

    const aTitle = document.getElementById("diffVersionATitle");
    const aScore = document.getElementById("diffVersionAScore");
    const aKeywords = document.getElementById("diffVersionAKeywords");
    const aMissing = document.getElementById("diffVersionAMissing");
    const aGaps = document.getElementById("diffVersionAGaps");

    const bTitle = document.getElementById("diffVersionBTitle");
    const bScore = document.getElementById("diffVersionBScore");
    const bNewKeywords = document.getElementById("diffVersionBNewKeywords");
    const bResolvedGaps = document.getElementById("diffVersionBResolvedGaps");
    const bKeywords = document.getElementById("diffVersionBKeywords");

    if (aTitle) aTitle.innerHTML = `<i class="fa-solid fa-clock-rotate-left me-1"></i> Version ${a.version_number} (Baseline)`;
    if (aScore) aScore.innerText = `ATS: ${a.ats_score}/100`;

    if (aKeywords) {
      aKeywords.innerHTML = "";
      const kwList = Array.isArray(a.keywords_found) ? a.keywords_found : [];
      if (kwList.length > 0) {
        kwList.forEach(k => {
          const span = document.createElement("span");
          span.className = "badge bg-white text-secondary border rounded-pill";
          span.innerText = k;
          aKeywords.appendChild(span);
        });
      } else {
        aKeywords.innerHTML = '<span class="text-muted small">None recorded</span>';
      }
    }

    if (aMissing) {
      aMissing.innerHTML = "";
      const mList = Array.isArray(a.keywords_missing) ? a.keywords_missing : [];
      if (mList.length > 0) {
        mList.forEach(k => {
          const span = document.createElement("span");
          span.className = "badge bg-danger-subtle text-danger border border-danger-subtle rounded-pill";
          span.innerText = k;
          aMissing.appendChild(span);
        });
      } else {
        aMissing.innerHTML = '<span class="text-muted small">None</span>';
      }
    }

    if (aGaps) {
      aGaps.innerHTML = "";
      const gList = Array.isArray(a.skill_gaps) ? a.skill_gaps : [];
      gList.forEach(g => {
        const div = document.createElement("div");
        div.className = "text-secondary mb-1";
        div.innerHTML = `<i class="fa-solid fa-circle-minus me-1 text-danger"></i> ${escapeHtml(g)}`;
        aGaps.appendChild(div);
      });
    }

    if (bTitle) bTitle.innerHTML = `<i class="fa-solid fa-star me-1"></i> Version ${b.version_number} (Active)`;
    if (bScore) bScore.innerText = `ATS: ${b.ats_score}/100`;

    if (bNewKeywords) {
      bNewKeywords.innerHTML = "";
      const newly = Array.isArray(d.newly_matched_keywords) ? d.newly_matched_keywords : [];
      if (newly.length > 0) {
        newly.forEach(k => {
          const span = document.createElement("span");
          span.className = "badge bg-success text-white rounded-pill";
          span.innerHTML = `<i class="fa-solid fa-plus me-1"></i>${escapeHtml(k)}`;
          bNewKeywords.appendChild(span);
        });
      } else {
        bNewKeywords.innerHTML = '<span class="text-muted small">No new keywords identified in this iteration</span>';
      }
    }

    if (bResolvedGaps) {
      bResolvedGaps.innerHTML = "";
      const resolved = Array.isArray(d.resolved_skill_gaps) ? d.resolved_skill_gaps : [];
      if (resolved.length > 0) {
        resolved.forEach(g => {
          const span = document.createElement("span");
          span.className = "badge bg-primary text-white rounded-pill";
          span.innerHTML = `<i class="fa-solid fa-check me-1"></i>${escapeHtml(g)}`;
          bResolvedGaps.appendChild(span);
        });
      } else {
        bResolvedGaps.innerHTML = '<span class="text-muted small">None resolved in this iteration</span>';
      }
    }

    if (bKeywords) {
      bKeywords.innerHTML = "";
      const bKw = Array.isArray(b.keywords_found) ? b.keywords_found : [];
      bKw.forEach(k => {
        const span = document.createElement("span");
        span.className = "badge bg-white text-dark border rounded-pill";
        span.innerText = k;
        bKeywords.appendChild(span);
      });
    }
  }

  function escapeHtml(str) {
    if (typeof str !== "string") str = String(str);
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
}

