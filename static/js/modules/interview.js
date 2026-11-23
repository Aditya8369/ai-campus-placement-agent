/**
 * Mock Interview Module (static/js/modules/interview.js)
 * =====================================================
 * Live interactive mock interview simulation with Voice-Enabled AI Interviewer:
 * - Real-time Web Speech API recognition (Speech-to-Text) with continuous interim transcription
 * - Audio visualizer wave animation and recording timer
 * - Pre-submission editable transcript review
 * - Speech Synthesis (Text-to-Speech) for interviewer questions with auto-speak toggle
 * - Dynamic verbal indicators evaluation (Verbal clarity, filler words, STAR method)
 * - Auto-save answer drafts, retry loops, completion modal, and transcript exports (#467, #475)
 */

import { escapeHtml, showToast, getCsrfToken } from "./utils.js";
import { clearAllInterviewDrafts, initInterviewDraftLogoutCleanup } from "./common.js";
import { handleRateLimitResponse, syncRateLimitFromHeaders, formatCountdown } from "./rate_limit.js";

export { clearAllInterviewDrafts, initInterviewDraftLogoutCleanup };

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
export function initMockInterview() {
  const chatForm = document.getElementById("chatForm");
  if (!chatForm) {
    if (document.getElementById("btnResetSession") || document.getElementById("inlineStrengthsWeaknessesCard")) {
      clearAllInterviewDrafts();
    }
    return;
  }

  const analysisId = chatForm.getAttribute("data-analysis-id") || "";
  const sessionId = chatForm.getAttribute("data-session-id") || analysisId;

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

  // Pause and Resume Elements (#265)
  const btnPauseResumeSession = document.getElementById("btnPauseResumeSession");
  const btnPauseResumeLabel = document.getElementById("btnPauseResumeLabel");
  const sessionStatusBadge = document.getElementById("sessionStatusBadge");
  const sessionStatusText = document.getElementById("sessionStatusText");

  // Video Coach & Composure Telemetry Elements
  const btnToggleVideoCoach = document.getElementById("btnToggleVideoCoach");
  const videoCoachPanel = document.getElementById("videoCoachPanel");
  const btnStopCamera = document.getElementById("btnStopCamera");
  const candidateVideoFeed = document.getElementById("candidateVideoFeed");
  const videoAnalysisCanvas = document.getElementById("videoAnalysisCanvas");
  const cameraStatusText = document.getElementById("cameraStatusText");
  const telemetryEyeScore = document.getElementById("telemetryEyeScore");
  const telemetryEyeStatus = document.getElementById("telemetryEyeStatus");
  const telemetryComposureScore = document.getElementById("telemetryComposureScore");
  const telemetryComposureStatus = document.getElementById("telemetryComposureStatus");
  const telemetryCadenceWpm = document.getElementById("telemetryCadenceWpm");
  const telemetryCadenceStatus = document.getElementById("telemetryCadenceStatus");
  const telemetryFillerCount = document.getElementById("telemetryFillerCount");
  const telemetryFillerList = document.getElementById("telemetryFillerList");

  // State trackers
  let recognition = null;
  let isRecording = false;
  let speechTimerInterval = null;
  let speechSeconds = 0;
  let activeUtteranceBtn = null;

  // Video Coach & Composure States
  let videoStream = null;
  let videoAnalysisInterval = null;
  let eyeCenteredFrames = 0;
  let totalVideoFrames = 0;
  let prevFramePixels = null;
  let composureHistory = [];
  let answerTypingStartTime = null;
  let lastMeasuredWpm = 130;
  let lastMeasuredFillerCount = 0;

  // Timed Answer Mode Elements & State (#431)
  const toggleTimedMode = document.getElementById("toggleTimedMode");
  const timedModeConfigDropdown = document.getElementById("timedModeConfigDropdown");
  const btnTimedConfig = document.getElementById("btnTimedConfig");
  const timedConfigLabel = document.getElementById("timedConfigLabel");
  const selectTechTimeLimit = document.getElementById("selectTechTimeLimit");
  const selectBehavTimeLimit = document.getElementById("selectBehavTimeLimit");
  const selectHrTimeLimit = document.getElementById("selectHrTimeLimit");
  const interviewTimerBar = document.getElementById("interviewTimerBar");
  const timerCountdownBadge = document.getElementById("timerCountdownBadge");
  const timerCountdownText = document.getElementById("timerCountdownText");
  const timerAllocatedText = document.getElementById("timerAllocatedText");
  const timerProgressBar = document.getElementById("timerProgressBar");
  const timerStatusNotice = document.getElementById("timerStatusNotice");
  const interviewTimerAnnouncer = document.getElementById("interviewTimerAnnouncer");

  let isTimedMode = false;
  let timerInterval = null;
  let allocatedSeconds = 120;
  let remainingSeconds = 120;
  let questionStartTime = Date.now();
  let hasAutoSubmitted = false;
  let isTimerPaused = false;

  const timeLimits = {
    technical: parseInt(localStorage.getItem("mock_interview_limit_tech") || "120", 10),
    behavioral: parseInt(localStorage.getItem("mock_interview_limit_behav") || "180", 10),
    hr: parseInt(localStorage.getItem("mock_interview_limit_hr") || "120", 10),
    default: 120,
  };

  if (selectTechTimeLimit) selectTechTimeLimit.value = String(timeLimits.technical);
  if (selectBehavTimeLimit) selectBehavTimeLimit.value = String(timeLimits.behavioral);
  if (selectHrTimeLimit) selectHrTimeLimit.value = String(timeLimits.hr);

  function updateTimedConfigLabel() {
    if (!timedConfigLabel) return;
    const tMin = (timeLimits.technical / 60).toFixed(timeLimits.technical % 60 ? 1 : 0);
    const bMin = (timeLimits.behavioral / 60).toFixed(timeLimits.behavioral % 60 ? 1 : 0);
    timedConfigLabel.textContent = `${tMin}m Tech / ${bMin}m Behav`;
  }
  updateTimedConfigLabel();

  function formatCountdownTime(totalSecs) {
    const s = Math.max(0, Math.floor(totalSecs));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function getQuestionTimeLimit(qType) {
    const t = (qType || "").toLowerCase();
    if (t.includes("behav")) return timeLimits.behavioral;
    if (t.includes("tech")) return timeLimits.technical;
    if (t.includes("hr")) return timeLimits.hr;
    return timeLimits.default;
  }

  function announceTimerWarning(message) {
    if (!interviewTimerAnnouncer) return;
    interviewTimerAnnouncer.textContent = "";
    setTimeout(() => {
      interviewTimerAnnouncer.textContent = message;
    }, 50);
  }

  function stopQuestionTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }

  function startQuestionTimer(qType) {
    stopQuestionTimer();
    if (!isTimedMode || !interviewTimerBar) {
      if (interviewTimerBar) interviewTimerBar.classList.add("d-none");
      return;
    }

    allocatedSeconds = getQuestionTimeLimit(qType);
    remainingSeconds = allocatedSeconds;
    questionStartTime = Date.now();
    hasAutoSubmitted = false;
    isTimerPaused = false;

    interviewTimerBar.classList.remove("d-none");
    if (timerAllocatedText) timerAllocatedText.textContent = `Allocated: ${formatCountdownTime(allocatedSeconds)}`;
    if (timerCountdownText) timerCountdownText.textContent = formatCountdownTime(remainingSeconds);

    if (timerCountdownBadge) {
      timerCountdownBadge.className = "badge bg-primary-subtle text-primary border border-primary-subtle rounded-pill px-3 py-2 font-monospace fs-6 fw-bold";
    }
    if (timerProgressBar) {
      timerProgressBar.className = "progress-bar bg-primary";
      timerProgressBar.style.width = "100%";
      timerProgressBar.setAttribute("aria-valuenow", "100");
    }
    if (timerStatusNotice) {
      timerStatusNotice.innerHTML = '<i class="fa-solid fa-hourglass-half text-primary me-1"></i> Timed Mode Active';
    }
    if (answerInput) {
      answerInput.classList.remove("border-danger");
    }

    timerInterval = setInterval(() => {
      if (isTimerPaused) return;

      remainingSeconds--;
      if (timerCountdownText) timerCountdownText.textContent = formatCountdownTime(remainingSeconds);

      const percent = Math.max(0, Math.round((remainingSeconds / allocatedSeconds) * 100));
      if (timerProgressBar) {
        timerProgressBar.style.width = `${percent}%`;
        timerProgressBar.setAttribute("aria-valuenow", String(percent));
      }

      // In the last 15 seconds: color change to warning/danger (#431)
      if (remainingSeconds <= 15 && remainingSeconds > 0) {
        if (timerCountdownBadge && !timerCountdownBadge.classList.contains("bg-danger")) {
          timerCountdownBadge.className = "badge bg-danger text-white border border-danger rounded-pill px-3 py-2 font-monospace fs-6 fw-bold shadow-sm";
        }
        if (timerProgressBar && !timerProgressBar.classList.contains("bg-danger")) {
          timerProgressBar.className = "progress-bar bg-danger progress-bar-striped progress-bar-animated";
        }
        if (timerStatusNotice) {
          timerStatusNotice.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-danger me-1"></i> ${remainingSeconds}s remaining! Auto-submitting soon...`;
        }
        if (answerInput) {
          answerInput.classList.add("border-danger");
        }

        // Accessible time warnings (#431)
        if (remainingSeconds === 15) {
          announceTimerWarning("15 seconds remaining. Your response will auto-submit when the countdown reaches zero.");
        } else if (remainingSeconds === 5) {
          announceTimerWarning("5 seconds remaining.");
        }
      }

      // Time runs out: auto-submit what has been typed (#431)
      if (remainingSeconds <= 0) {
        stopQuestionTimer();
        if (timerCountdownText) timerCountdownText.textContent = "00:00";
        if (timerProgressBar) timerProgressBar.style.width = "0%";
        if (timerStatusNotice) {
          timerStatusNotice.innerHTML = '<i class="fa-solid fa-stopwatch text-danger me-1"></i> Time\'s up! Auto-submitting response...';
        }
        announceTimerWarning("Time expired! Auto-submitting your response.");

        if (!hasAutoSubmitted) {
          hasAutoSubmitted = true;
          autoSubmitAnswer();
        }
      }
    }, 1000);
  }

  function autoSubmitAnswer() {
    if (!chatForm) return;
    const sessionPaused = sessionStatusText?.innerText?.trim().toLowerCase() === "paused";
    if (sessionPaused) return;

    if (answerInput && !answerInput.value.trim()) {
      answerInput.value = "(Time expired - auto-submitted)";
    }
    chatForm.requestSubmit();
  }

  // Initialize Timed Mode from saved setting (default is OFF - untimed) (#431)
  const savedTimed = localStorage.getItem("mock_interview_timed_mode") === "true";
  if (toggleTimedMode) {
    toggleTimedMode.checked = savedTimed;
    isTimedMode = savedTimed;
    if (timedModeConfigDropdown) {
      if (isTimedMode) timedModeConfigDropdown.classList.remove("d-none");
      else timedModeConfigDropdown.classList.add("d-none");
    }

    toggleTimedMode.addEventListener("change", () => {
      isTimedMode = toggleTimedMode.checked;
      localStorage.setItem("mock_interview_timed_mode", isTimedMode ? "true" : "false");
      if (timedModeConfigDropdown) {
        if (isTimedMode) timedModeConfigDropdown.classList.remove("d-none");
        else timedModeConfigDropdown.classList.add("d-none");
      }

      const activeQType = chatForm.getAttribute("data-question-type") || "Technical";
      if (isTimedMode) {
        startQuestionTimer(activeQType);
        if (typeof showToast === "function") {
          showToast(`Timed Mode enabled: ${formatCountdownTime(getQuestionTimeLimit(activeQType))} limit for this question.`);
        }
      } else {
        stopQuestionTimer();
        if (interviewTimerBar) interviewTimerBar.classList.add("d-none");
        if (answerInput) answerInput.classList.remove("border-danger");
        if (typeof showToast === "function") {
          showToast("Timed Mode disabled. Untimed practice active.");
        }
      }
    });
  }

  if (selectTechTimeLimit) {
    selectTechTimeLimit.addEventListener("change", () => {
      timeLimits.technical = parseInt(selectTechTimeLimit.value, 10);
      localStorage.setItem("mock_interview_limit_tech", String(timeLimits.technical));
      updateTimedConfigLabel();
      const activeQType = chatForm.getAttribute("data-question-type") || "Technical";
      if (isTimedMode && activeQType.toLowerCase().includes("tech")) {
        startQuestionTimer(activeQType);
      }
    });
  }
  if (selectBehavTimeLimit) {
    selectBehavTimeLimit.addEventListener("change", () => {
      timeLimits.behavioral = parseInt(selectBehavTimeLimit.value, 10);
      localStorage.setItem("mock_interview_limit_behav", String(timeLimits.behavioral));
      updateTimedConfigLabel();
      const activeQType = chatForm.getAttribute("data-question-type") || "Technical";
      if (isTimedMode && activeQType.toLowerCase().includes("behav")) {
        startQuestionTimer(activeQType);
      }
    });
  }
  if (selectHrTimeLimit) {
    selectHrTimeLimit.addEventListener("change", () => {
      timeLimits.hr = parseInt(selectHrTimeLimit.value, 10);
      localStorage.setItem("mock_interview_limit_hr", String(timeLimits.hr));
      updateTimedConfigLabel();
      const activeQType = chatForm.getAttribute("data-question-type") || "Technical";
      if (isTimedMode && activeQType.toLowerCase().includes("hr")) {
        startQuestionTimer(activeQType);
      }
    });
  }

  // Start question timer on initial load if timed mode is enabled
  const initialQType = chatForm.getAttribute("data-question-type") || "Technical";
  if (isTimedMode) {
    startQuestionTimer(initialQType);
  }

  // -------------------------------------------------------------
  // Web MediaStream Video Coach & Non-Verbal Composure Analyzer
  // -------------------------------------------------------------
  async function startVideoCoach() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Camera access via MediaStream API is not supported in this browser environment.");
      return;
    }
    try {
      if (cameraStatusText) cameraStatusText.textContent = "Requesting camera permission...";
      videoStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 320 }, height: { ideal: 240 }, facingMode: "user" },
        audio: false,
      });

      if (candidateVideoFeed) {
        candidateVideoFeed.srcObject = videoStream;
        candidateVideoFeed.play().catch(() => {});
      }
      if (videoCoachPanel) videoCoachPanel.classList.remove("d-none");
      if (cameraStatusText) cameraStatusText.textContent = "Live camera active (Tracking non-verbal composure)";
      if (btnToggleVideoCoach) {
        btnToggleVideoCoach.classList.remove("btn-outline-secondary");
        btnToggleVideoCoach.classList.add("btn-primary");
      }

      eyeCenteredFrames = 0;
      totalVideoFrames = 0;
      prevFramePixels = null;
      composureHistory = [];

      startVideoAnalysisLoop();
    } catch (err) {
      console.error("Camera access error:", err);
      if (cameraStatusText) cameraStatusText.textContent = "Camera access denied or unavailable";
      alert("Could not access camera for non-verbal posture analysis. Please grant camera permission in your browser.");
    }
  }

  function stopVideoCoach() {
    if (videoAnalysisInterval) {
      clearInterval(videoAnalysisInterval);
      videoAnalysisInterval = null;
    }
    if (videoStream) {
      videoStream.getTracks().forEach((track) => track.stop());
      videoStream = null;
    }
    if (candidateVideoFeed) {
      candidateVideoFeed.srcObject = null;
    }
    if (videoCoachPanel) videoCoachPanel.classList.add("d-none");
    if (btnToggleVideoCoach) {
      btnToggleVideoCoach.classList.remove("btn-primary");
      btnToggleVideoCoach.classList.add("btn-outline-secondary");
    }
    if (cameraStatusText) cameraStatusText.textContent = "Camera standby";
  }

  function startVideoAnalysisLoop() {
    if (videoAnalysisInterval) clearInterval(videoAnalysisInterval);
    const ctx = videoAnalysisCanvas ? videoAnalysisCanvas.getContext("2d", { willReadFrequently: true }) : null;

    videoAnalysisInterval = setInterval(() => {
      if (!candidateVideoFeed || candidateVideoFeed.readyState < 2 || !ctx) return;

      totalVideoFrames++;
      ctx.drawImage(candidateVideoFeed, 0, 0, 160, 120);
      const frame = ctx.getImageData(0, 0, 160, 120);
      const data = frame.data;

      // 1. Center quadrant eye-contact presence estimation
      let centerLuminance = 0;
      let centerCount = 0;
      for (let y = 20; y < 85; y += 4) {
        for (let x = 40; x < 120; x += 4) {
          const idx = (y * 160 + x) * 4;
          centerLuminance += 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
          centerCount++;
        }
      }
      const avgCenter = centerCount > 0 ? centerLuminance / centerCount : 128;
      const isCentered = avgCenter > 25 && avgCenter < 235;
      if (isCentered) eyeCenteredFrames++;

      const eyeScore = Math.min(100, Math.max(35, Math.round((eyeCenteredFrames / totalVideoFrames) * 100)));
      if (telemetryEyeScore) telemetryEyeScore.textContent = `${eyeScore}%`;
      if (telemetryEyeStatus) {
        if (eyeScore >= 75) {
          telemetryEyeStatus.textContent = "Good Center Focus";
          telemetryEyeStatus.className = "text-success fw-semibold";
        } else if (eyeScore >= 50) {
          telemetryEyeStatus.textContent = "Intermittent";
          telemetryEyeStatus.className = "text-warning fw-semibold";
        } else {
          telemetryEyeStatus.textContent = "Looking Away";
          telemetryEyeStatus.className = "text-danger fw-semibold";
        }
      }

      // 2. Motion velocity delta for Composure estimation
      if (prevFramePixels) {
        let diffSum = 0;
        const sampleCount = data.length / 16;
        for (let i = 0; i < data.length; i += 16) {
          diffSum += Math.abs(data[i] - prevFramePixels[i]);
        }
        const avgDelta = diffSum / sampleCount;
        let frameComposure = 90;
        if (avgDelta < 15) {
          frameComposure = 90 - Math.round(avgDelta);
        } else {
          frameComposure = Math.max(40, 80 - Math.round((avgDelta - 15) * 2));
        }
        composureHistory.push(frameComposure);
        if (composureHistory.length > 25) composureHistory.shift();

        const avgComposure = Math.round(composureHistory.reduce((a, b) => a + b, 0) / composureHistory.length);
        if (telemetryComposureScore) telemetryComposureScore.textContent = `${avgComposure}%`;
        if (telemetryComposureStatus) {
          if (avgComposure >= 75) {
            telemetryComposureStatus.textContent = "Calm & Steady";
            telemetryComposureStatus.className = "text-primary fw-semibold";
          } else if (avgComposure >= 55) {
            telemetryComposureStatus.textContent = "Mild Movement";
            telemetryComposureStatus.className = "text-warning fw-semibold";
          } else {
            telemetryComposureStatus.textContent = "Restless Motion";
            telemetryComposureStatus.className = "text-danger fw-semibold";
          }
        }
      }
      prevFramePixels = new Uint8Array(data);
    }, 400);
  }

  if (btnToggleVideoCoach) {
    btnToggleVideoCoach.addEventListener("click", () => {
      if (videoStream) {
        stopVideoCoach();
      } else {
        startVideoCoach();
      }
    });
  }

  if (btnStopCamera) {
    btnStopCamera.addEventListener("click", () => {
      stopVideoCoach();
    });
  }

  // Live Speech Cadence & Verbal Filler Analyzer
  const FILLER_WORDS_REGEX = /\b(um+|uh+|like|you know|actually|basically|literally|sort of|kind of|i mean|so yeah)\b/gi;

  function updateLiveSpeechTelemetry(text) {
    if (!text) {
      if (telemetryCadenceWpm) telemetryCadenceWpm.textContent = "-- WPM";
      if (telemetryFillerCount) telemetryFillerCount.textContent = "0";
      return;
    }
    const words = text.split(/\s+/).filter(Boolean);
    const wordCount = words.length;

    if (!answerTypingStartTime && wordCount > 0) {
      answerTypingStartTime = Date.now();
    }

    if (answerTypingStartTime && wordCount >= 3) {
      const elapsedMinutes = (Date.now() - answerTypingStartTime) / 60000;
      const wpm = elapsedMinutes > 0.04 ? Math.round(wordCount / elapsedMinutes) : 130;
      lastMeasuredWpm = wpm;
      if (telemetryCadenceWpm) telemetryCadenceWpm.textContent = `${wpm} WPM`;
      if (telemetryCadenceStatus) {
        if (wpm >= 110 && wpm <= 165) {
          telemetryCadenceStatus.textContent = "Optimal Pacing";
          telemetryCadenceStatus.className = "text-success fw-semibold";
        } else if (wpm > 165) {
          telemetryCadenceStatus.textContent = "Too Fast";
          telemetryCadenceStatus.className = "text-warning fw-semibold";
        } else {
          telemetryCadenceStatus.textContent = "Slow Delivery";
          telemetryCadenceStatus.className = "text-secondary fw-semibold";
        }
      }
    }

    const fillerMatches = text.match(FILLER_WORDS_REGEX) || [];
    lastMeasuredFillerCount = fillerMatches.length;
    if (telemetryFillerCount) telemetryFillerCount.textContent = String(fillerMatches.length);
    if (telemetryFillerList) {
      if (fillerMatches.length > 0) {
        const unique = Array.from(new Set(fillerMatches.map((f) => f.toLowerCase())));
        telemetryFillerList.textContent = unique.slice(0, 3).join(", ");
        telemetryFillerList.className = "text-warning fw-semibold text-truncate";
      } else {
        telemetryFillerList.textContent = "Clean speech";
        telemetryFillerList.className = "text-success";
      }
    }
  }

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

  // Delegated click listener for all TTS and Try-Again retry buttons (initial & dynamically added)
  if (chatContainer) {
    chatContainer.addEventListener("click", (e) => {
      const ttsBtn = e.target.closest(".btn-tts");
      if (ttsBtn) {
        e.preventDefault();
        const textToSpeak = ttsBtn.getAttribute("data-tts") || ttsBtn.closest(".chat-bubble-agent")?.innerText || "";
        speakQuestionText(textToSpeak, ttsBtn);
        return;
      }

      // Try-Again Retry Loop Action (#467)
      const tryBtn = e.target.closest(".btn-try-again");
      if (tryBtn) {
        e.preventDefault();
        const qIndex = tryBtn.getAttribute("data-question-index");
        const retriesLeft = parseInt(tryBtn.getAttribute("data-retries-left") || "2", 10);
        if (retriesLeft <= 0) return;

        // Remember previous active question index before entering retry mode
        if (!chatForm.getAttribute("data-previous-active-index")) {
          chatForm.setAttribute("data-previous-active-index", chatForm.getAttribute("data-question-index") || "0");
        }

        // Set retry state on the form
        chatForm.setAttribute("data-is-retry", "true");
        chatForm.setAttribute("data-question-index", qIndex);

        // Display retry banner above the input area
        let retryBanner = document.getElementById("retryAlertBanner");
        if (!retryBanner) {
          retryBanner = document.createElement("div");
          retryBanner.id = "retryAlertBanner";
          retryBanner.className = "alert alert-info py-2 px-3 mb-2 d-flex justify-content-between align-items-center rounded-3 shadow-xs";
          chatForm.insertBefore(retryBanner, chatForm.firstChild);
        }
        retryBanner.innerHTML = `
          <div class="small">
            <i class="fa-solid fa-rotate-left text-primary me-1"></i>
            <strong>Retrying Question ${parseInt(qIndex, 10) + 1}</strong>: Refine your response using the feedback above (${retriesLeft} ${retriesLeft === 1 ? 'retry' : 'retries'} remaining).
          </div>
          <button type="button" class="btn-close btn-sm" id="btnCancelRetry" aria-label="Cancel retry"></button>
        `;

        const cancelBtn = retryBanner.querySelector("#btnCancelRetry");
        if (cancelBtn) {
          cancelBtn.addEventListener("click", () => {
            retryBanner.remove();
            chatForm.removeAttribute("data-is-retry");
            const prevIndex = chatForm.getAttribute("data-previous-active-index");
            if (prevIndex !== null) {
              chatForm.setAttribute("data-question-index", prevIndex);
              chatForm.removeAttribute("data-previous-active-index");
            }
            submitBtn.innerHTML = "Submit Answer";
          });
        }

        submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane me-1"></i> Submit Refined Answer';
        if (answerInput) {
          answerInput.disabled = false;
          submitBtn.disabled = false;
          answerInput.value = "";
          answerInput.focus();
          answerInput.scrollIntoView({ behavior: "smooth", block: "center" });
        }
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
  // 1b. Pause and Resume Mock Interview Logic (#265)
  // -------------------------------------------------------------
  if (btnPauseResumeSession) {
    let isCurrentlyPaused = sessionStatusText?.innerText?.trim().toLowerCase() === "paused";

    function updatePauseUI(isPaused) {
      isCurrentlyPaused = isPaused;
      if (isPaused) {
        if (btnPauseResumeLabel) btnPauseResumeLabel.innerText = "Resume Interview";
        btnPauseResumeSession.innerHTML = '<i class="fa-solid fa-play me-1"></i> <span id="btnPauseResumeLabel">Resume Interview</span>';
        btnPauseResumeSession.classList.remove("btn-outline-warning");
        btnPauseResumeSession.classList.add("btn-warning");
        if (sessionStatusBadge) {
          sessionStatusBadge.className = "badge rounded-pill py-2 px-3 small bg-warning text-dark";
          sessionStatusBadge.innerHTML = '<i class="fa-solid fa-circle-pause me-1"></i> Status: <span id="sessionStatusText">Paused</span>';
        }
        if (btnSendAnswer) btnSendAnswer.disabled = true;
        if (answerInput) {
          answerInput.placeholder = "Interview is currently PAUSED. Click 'Resume Interview' above to continue.";
        }
        isTimerPaused = true;
        if (timerStatusNotice) {
          timerStatusNotice.innerHTML = '<i class="fa-solid fa-circle-pause text-warning me-1"></i> Timer Paused';
        }
      } else {
        if (btnPauseResumeLabel) btnPauseResumeLabel.innerText = "Pause Interview";
        btnPauseResumeSession.innerHTML = '<i class="fa-solid fa-pause me-1"></i> <span id="btnPauseResumeLabel">Pause Interview</span>';
        btnPauseResumeSession.classList.remove("btn-warning");
        btnPauseResumeSession.classList.add("btn-outline-warning");
        if (sessionStatusBadge) {
          sessionStatusBadge.className = "badge rounded-pill py-2 px-3 small bg-info text-dark";
          sessionStatusBadge.innerHTML = '<i class="fa-solid fa-circle-play me-1"></i> Status: <span id="sessionStatusText">In Progress</span>';
        }
        if (btnSendAnswer) btnSendAnswer.disabled = false;
        if (answerInput) {
          answerInput.placeholder = "Type your response here or click 'Speak' to answer using your microphone...";
        }
        isTimerPaused = false;
        if (timerStatusNotice) {
          timerStatusNotice.innerHTML = '<i class="fa-solid fa-hourglass-half text-primary me-1"></i> Timed Mode Active';
        }
      }
    }

    if (isCurrentlyPaused) {
      updatePauseUI(true);
    }

    btnPauseResumeSession.addEventListener("click", async () => {
      const targetSessionId = sessionId || analysisId;
      if (!targetSessionId) return;

      if (!isCurrentlyPaused) {
        // Trigger PAUSE
        const draft = answerInput ? answerInput.value : "";
        btnPauseResumeSession.disabled = true;
        try {
          const resp = await fetch(`/api/interview/${encodeURIComponent(targetSessionId)}/pause`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || ""
            },
            body: JSON.stringify({
              draft_answer: draft,
              question_index: currentQuestionIdx
            })
          });
          const res = await resp.json();
          if (res.status === "success") {
            updatePauseUI(true);
            if (typeof showToast === "function") {
              showToast("Interview paused. Your progress and answer draft have been saved securely.");
            }
          }
        } catch (err) {
          console.error("Failed to pause interview session:", err);
        } finally {
          btnPauseResumeSession.disabled = false;
        }
      } else {
        // Trigger RESUME
        btnPauseResumeSession.disabled = true;
        try {
          const resp = await fetch(`/api/interview/${encodeURIComponent(targetSessionId)}/resume`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || ""
            }
          });
          const res = await resp.json();
          if (res.status === "success") {
            updatePauseUI(false);
            if (res.data?.draft_answer && answerInput && !answerInput.value) {
              answerInput.value = res.data.draft_answer;
            }
            if (typeof showToast === "function") {
              showToast("Interview resumed! Welcome back.");
            }
          }
        } catch (err) {
          console.error("Failed to resume interview session:", err);
        } finally {
          btnPauseResumeSession.disabled = false;
        }
      }
    });
  }

  // -------------------------------------------------------------
  // Mock Interview Session Reset / Restart Capability (#496)
  // -------------------------------------------------------------
  const btnResetSession = document.getElementById("btnResetSession");
  const modalBtnRestartSession = document.getElementById("modalBtnRestartSession");

  const handleResetSession = async () => {
    if (!confirm("Are you sure you want to restart this interview session? Your answers for this round will be cleared and you can practice again from Question 1.")) {
      return;
    }
    const targetSessionId = sessionId || analysisId;
    if (!targetSessionId) return;

    try {
      if (btnResetSession) btnResetSession.disabled = true;
      if (modalBtnRestartSession) modalBtnRestartSession.disabled = true;
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      const resp = await fetch(`/interview/${encodeURIComponent(analysisId)}/reset?session_id=${encodeURIComponent(targetSessionId)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ session_id: targetSessionId }),
      });
      const res = await resp.json();
      if (res.success) {
        if (typeof clearAllDraftsForThisSession === "function") {
          clearAllDraftsForThisSession();
        }
        window.location.reload();
      } else {
        alert(res.error || "Failed to reset interview session.");
      }
    } catch (err) {
      console.error("Failed to reset interview session:", err);
      alert("Error resetting interview session. Please try again.");
    } finally {
      if (btnResetSession) btnResetSession.disabled = false;
      if (modalBtnRestartSession) modalBtnRestartSession.disabled = false;
    }
  };

  if (btnResetSession) {
    btnResetSession.addEventListener("click", handleResetSession);
  }
  if (modalBtnRestartSession) {
    modalBtnRestartSession.addEventListener("click", handleResetSession);
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
          if (typeof saveCurrentDraft === "function") saveCurrentDraft();
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
  // 3. Live Word Counter, Keyboard Shortcuts & Draft Autosave (#475)
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

  const draftStatusBadge = document.getElementById("draftStatusBadge");
  let draftIndicatorTimer = null;
  let lastSavedDraftText = "";
  let draftDebounceTimer = null;

  function showDraftIndicator(message, persistent = false) {
    if (!draftStatusBadge) return;
    if (draftIndicatorTimer) {
      clearTimeout(draftIndicatorTimer);
      draftIndicatorTimer = null;
    }
    const isRestored = message.toLowerCase().includes("restored");
    const icon = isRestored
      ? '<i class="fa-solid fa-clock-rotate-left text-success me-1"></i>'
      : '<i class="fa-regular fa-floppy-disk text-primary me-1"></i>';
    draftStatusBadge.innerHTML = `${icon}<span>${message}</span>`;
    draftStatusBadge.classList.remove("d-none");
    if (!persistent) {
      draftIndicatorTimer = setTimeout(() => {
        draftStatusBadge.classList.add("d-none");
      }, 3000);
    }
  }

  function hideDraftIndicator() {
    if (!draftStatusBadge) return;
    if (draftIndicatorTimer) {
      clearTimeout(draftIndicatorTimer);
      draftIndicatorTimer = null;
    }
    draftStatusBadge.classList.add("d-none");
  }

  function getDraftStorageKey(qIndex) {
    const q = (typeof qIndex !== "undefined" && qIndex !== null)
      ? qIndex
      : parseInt(chatForm.getAttribute("data-question-index") || "0", 10);
    const targetSession = chatForm.getAttribute("data-session-id") || chatForm.getAttribute("data-analysis-id") || sessionId || analysisId || "";
    return `interview_draft_${targetSession}_${q}`;
  }

  function saveCurrentDraft() {
    if (!answerInput) return;
    const currentText = answerInput.value;
    const currentQ = parseInt(chatForm.getAttribute("data-question-index") || "0", 10);
    const key = getDraftStorageKey(currentQ);

    if (currentText && currentText.trim().length > 0) {
      if (currentText !== lastSavedDraftText) {
        try {
          localStorage.setItem(key, currentText);
          lastSavedDraftText = currentText;
          showDraftIndicator("Draft saved");
        } catch (err) {
          console.warn("Unable to save interview draft to localStorage:", err);
        }
      }
    } else {
      if (lastSavedDraftText) {
        try {
          localStorage.removeItem(key);
        } catch (e) {}
        lastSavedDraftText = "";
        hideDraftIndicator();
      }
    }
  }

  function restoreCurrentDraft() {
    if (!answerInput) return;
    const currentQ = parseInt(chatForm.getAttribute("data-question-index") || "0", 10);
    const key = getDraftStorageKey(currentQ);
    const targetSession = chatForm.getAttribute("data-session-id") || chatForm.getAttribute("data-analysis-id") || sessionId || "";
    const altAnalysisId = chatForm.getAttribute("data-analysis-id") || analysisId || "";

    try {
      let saved = localStorage.getItem(key);
      if (!saved && altAnalysisId && altAnalysisId !== targetSession) {
        saved = localStorage.getItem(`interview_draft_${altAnalysisId}_${currentQ}`);
      }

      if (saved && saved.trim().length > 0) {
        if (!answerInput.value || !answerInput.value.trim()) {
          answerInput.value = saved;
          lastSavedDraftText = saved;
          triggerWordCounter(answerInput);
          updateLiveSpeechTelemetry(answerInput.value);
          showDraftIndicator("Draft restored", true);
        }
      }
    } catch (err) {
      console.warn("Unable to restore interview draft from localStorage:", err);
    }
  }

  function clearDraftForQuestion(qIndex) {
    const currentQ = (typeof qIndex !== "undefined" && qIndex !== null)
      ? qIndex
      : parseInt(chatForm.getAttribute("data-question-index") || "0", 10);
    const key = getDraftStorageKey(currentQ);
    const altAnalysisId = chatForm.getAttribute("data-analysis-id") || analysisId || "";
    try {
      localStorage.removeItem(key);
      if (altAnalysisId) {
        localStorage.removeItem(`interview_draft_${altAnalysisId}_${currentQ}`);
      }
    } catch (e) {}
    lastSavedDraftText = "";
    hideDraftIndicator();
  }

  function clearAllDraftsForThisSession() {
    const targetSession = chatForm.getAttribute("data-session-id") || chatForm.getAttribute("data-analysis-id") || sessionId || "";
    const altAnalysisId = chatForm.getAttribute("data-analysis-id") || analysisId || "";
    try {
      const keysToRemove = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith("interview_draft_")) {
          if (!targetSession && !altAnalysisId) {
            keysToRemove.push(k);
          } else if ((targetSession && k.includes(`_${targetSession}_`)) || (altAnalysisId && k.includes(`_${altAnalysisId}_`))) {
            keysToRemove.push(k);
          }
        }
      }
      keysToRemove.forEach((k) => localStorage.removeItem(k));
    } catch (e) {}
    lastSavedDraftText = "";
    hideDraftIndicator();
  }

  // Restore unsent draft on page initialization (#475)
  restoreCurrentDraft();

  if (answerInput) {
    answerInput.addEventListener("input", () => {
      triggerWordCounter(answerInput);
      updateLiveSpeechTelemetry(answerInput.value);

      // Hide restored indicator once user resumes typing
      if (draftStatusBadge && draftStatusBadge.innerText.includes("restored")) {
        hideDraftIndicator();
      }

      // Debounced autosave (1.2 seconds after typing pause)
      if (draftDebounceTimer) clearTimeout(draftDebounceTimer);
      draftDebounceTimer = setTimeout(saveCurrentDraft, 1200);
    });

    // Periodic draft autosave every 2.5 seconds (#475)
    const draftAutosaveInterval = setInterval(saveCurrentDraft, 2500);

    // Persist draft immediately before accidental page unload or reload
    window.addEventListener("beforeunload", saveCurrentDraft);

    // Ctrl/Cmd + Enter submits only when the answer is not empty (#475)
    answerInput.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        const trimmed = (answerInput.value || "").trim();
        if (trimmed.length > 0) {
          chatForm.requestSubmit();
        }
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
      if (!confirm("Your answer is blank. Would you like to submit an empty response to receive guidance?")) {
        return;
      }
    }

    // Clear draft for this question upon submission (#475)
    const questionIndex = parseInt(chatForm.getAttribute("data-question-index") || "0", 10);
    clearDraftForQuestion(questionIndex);

    // Stop active speech recognition or TTS
    if (recognition && isRecording) {
      try { recognition.stop(); } catch (err) {}
      isRecording = false;
    }
    if (isSpeechSynthesisSupported) {
      window.speechSynthesis.cancel();
      resetSpeakingButtons();
    }

    // Stop active question countdown timer (#431)
    stopQuestionTimer();
    const isAnswerTimed = isTimedMode;
    let timeTakenSeconds = 0;
    let timeLimitSeconds = null;
    if (isAnswerTimed) {
      timeLimitSeconds = allocatedSeconds;
      timeTakenSeconds = Math.min(allocatedSeconds, Math.max(1, allocatedSeconds - remainingSeconds));
    } else {
      timeTakenSeconds = speechSeconds || (answerTypingStartTime ? Math.max(1, Math.round((Date.now() - answerTypingStartTime) / 1000)) : 30);
    }

    const analysisId = chatForm.getAttribute("data-analysis-id");

    // Compute final speech and non-verbal telemetry metrics
    const finalSpeechMetrics = {
      duration_seconds: speechSeconds || (answerTypingStartTime ? Math.max(5, Math.round((Date.now() - answerTypingStartTime) / 1000)) : 30),
      words_per_minute: lastMeasuredWpm || 130,
      filler_word_count: lastMeasuredFillerCount || 0,
      eye_contact_ratio: totalVideoFrames > 0 ? (eyeCenteredFrames / totalVideoFrames) : 0.85,
      composure_score: composureHistory.length > 0 ? Math.round(composureHistory.reduce((a, b) => a + b, 0) / composureHistory.length) : 85,
    };

    // Reset session timer counters for next answer
    answerTypingStartTime = null;

    // Disable inputs during evaluation
    answerInput.disabled = true;
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status"></span>`;

    // Append user answer bubble
    appendChatBubble(answer || "<i>(No answer provided)</i>", "user");
    answerInput.value = "";
    triggerWordCounter(answerInput);

    // Append loader bubble from Interview Agent
    const loaderBubble = appendChatBubble("<i>Interview Agent & STAR Story Coach are analyzing your response and verbal delivery...</i>", "agent");

    try {
      const isRetrySubmission = chatForm.getAttribute("data-is-retry") === "true";
      const response = await fetch(`/interview/${analysisId}/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          answer: answer,
          question_index: questionIndex,
          is_retry: isRetrySubmission,
          speech_metrics: finalSpeechMetrics,
          is_timed: isAnswerTimed,
          time_taken_seconds: timeTakenSeconds,
          time_limit_seconds: timeLimitSeconds,
        }),
      });

      const result = await response.json();
      loaderBubble.remove();

      // Clean up retry banner and form state after submission
      document.getElementById("retryAlertBanner")?.remove();
      chatForm.removeAttribute("data-is-retry");
      submitBtn.innerHTML = "Submit Answer";

      syncRateLimitFromHeaders(response, "interview_eval");

      if (response.status === 429 || result.retry_after || result.retry_after_seconds) {
        handleRateLimitResponse(response, result, {
          scope: "interview_eval",
          submitButton: submitBtn,
          countdownElement: document.getElementById("interviewCountdownTimer"),
          noticeContainer: document.getElementById("interviewRateLimitNotice"),
          messageElement: document.getElementById("interviewRateLimitMessage"),
        });
        const retryTime = formatCountdown(result.retry_after || result.retry_after_seconds || 60);
        appendChatBubble(
          result.message || `You have temporarily exceeded the request rate limit. You can try again in ${retryTime}.`,
          "agent"
        );
        resetInputs();
        submitBtn.disabled = true;
        return;
      }

      if (result.error) {
        appendChatBubble(`Error: ${result.error}`, "agent");
        resetInputs();
        return;
      }

      // Display dynamic feedback scores on dashboard panels
      renderEvaluationDetails(result.evaluation, questionIndex + 1);

      // Construct rich feedback bubble with verbal metrics and STAR pills
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
      const sa = evalData.star_analysis;
      if (sa && (sa.situation || sa.task || sa.action || sa.result)) {
        const getBadge = (val, label) => {
          const s = String(val || "").toLowerCase();
          if (s === "present") {
            return `<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-2 py-1 star-badge-present"><i class="fa-solid fa-check me-1"></i> ${label}: Present</span>`;
          } else if (s === "weak") {
            return `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-2 py-1 star-badge-weak"><i class="fa-solid fa-triangle-exclamation me-1"></i> ${label}: Weak</span>`;
          } else {
            return `<span class="badge bg-danger-subtle text-danger border border-danger-subtle rounded-pill px-2 py-1 star-badge-missing"><i class="fa-solid fa-xmark me-1"></i> ${label}: Missing</span>`;
          }
        };

        starHtml = `
          <div class="p-2 bg-light rounded-3 border mb-2 star-checklist-container">
            <div class="d-flex justify-content-between align-items-center mb-1">
              <small class="fw-bold text-dark"><i class="fa-solid fa-list-check text-primary me-1"></i> STAR Structure Checklist:</small>
            </div>
            <div class="d-flex flex-wrap gap-2 mb-1">
              ${getBadge(sa.situation, "Situation")}
              ${getBadge(sa.task, "Task")}
              ${getBadge(sa.action, "Action")}
              ${getBadge(sa.result, "Result")}
            </div>
            ${sa.tip ? `<div class="small text-muted mt-1 star-improvement-tip"><i class="fa-solid fa-lightbulb text-warning me-1"></i> <b>Improvement Tip:</b> ${escapeHtml(sa.tip)}</div>` : ""}
          </div>
        `;
      } else {
        const se = evalData.star_evaluation;
        if (se) {
          starHtml = `
            <div class="p-2 bg-white rounded-3 border mb-2">
              <div class="d-flex justify-content-between align-items-center mb-1">
                <small class="fw-bold text-dark"><i class="fa-solid fa-sitemap text-primary me-1"></i> STAR Story Breakdown</small>
                <span class="badge bg-primary-subtle text-primary border border-primary-subtle rounded-pill">STAR Score: ${se.star_score}/100</span>
              </div>
              <div class="d-flex flex-wrap gap-1 mb-1">
                <span class="badge ${se.situation.present ? 'bg-success-subtle text-success border border-success-subtle' : 'bg-danger-subtle text-danger border border-danger-subtle'} rounded-pill">S: ${se.situation.score}%</span>
                <span class="badge ${se.task.present ? 'bg-success-subtle text-success border border-success-subtle' : 'bg-danger-subtle text-danger border border-danger-subtle'} rounded-pill">T: ${se.task.score}%</span>
                <span class="badge ${se.action.present ? 'bg-success-subtle text-success border border-success-subtle' : 'bg-danger-subtle text-danger border border-danger-subtle'} rounded-pill">A: ${se.action.score}%</span>
                <span class="badge ${se.result.present ? 'bg-success-subtle text-success border border-success-subtle' : 'bg-danger-subtle text-danger border border-danger-subtle'} rounded-pill">R: ${se.result.score}%</span>
              </div>
              ${se.coaching && se.coaching.suggested_star_rewrite ? `<div class="small text-muted fst-italic"><b>Coach's Model Rewrite:</b> "${se.coaching.suggested_star_rewrite}"</div>` : ''}
            </div>
          `;
        } else if (evalData.star_method_analysis && evalData.star_method_analysis.feedback) {
          starHtml = `
            <div class="small mb-2 text-secondary">
              <i class="fa-solid fa-sitemap text-primary me-1"></i> <b>STAR Framework:</b> ${evalData.star_method_analysis.feedback}
            </div>
          `;
        }
      }

      const timeDisplayStr = result.time_display || evalData.time_display || "";
      let timingBadgeHtml = "";
      if (timeDisplayStr) {
        const formattedDisplay = timeDisplayStr.charAt(0).toUpperCase() + timeDisplayStr.slice(1);
        timingBadgeHtml = `
          <span class="badge bg-secondary-subtle text-dark border rounded-pill px-2 py-1 small">
            <i class="fa-regular fa-clock text-primary me-1"></i> ${escapeHtml(formattedDisplay)}
          </span>
        `;
      }

      let probingFollowUpHtml = "";
      if (evalData.probing_follow_up) {
        probingFollowUpHtml = `
          <div class="p-2 bg-warning-subtle text-warning-emphasis rounded-3 border border-warning-subtle mb-2 probing-follow-up-card">
            <div class="fw-bold small mb-1"><i class="fa-solid fa-bolt me-1"></i> Strict Technical Probing Follow-Up:</div>
            <div class="small">${escapeHtml(evalData.probing_follow_up)}</div>
          </div>
        `;
      }

      let perAnswerFeedbackHtml = "";
      if (evalData.clarity || evalData.structure || evalData.relevance || evalData.tip) {
        perAnswerFeedbackHtml = `
          <div class="p-3 bg-light rounded-3 border mb-2 per-answer-feedback-card">
            <div class="fw-bold text-dark small mb-2"><i class="fa-solid fa-layer-group text-primary me-1"></i> Answer Analysis &amp; Polish:</div>
            <div class="row g-2 mb-2">
              ${evalData.clarity ? `
                <div class="col-12 col-md-4">
                  <div class="bg-white p-2 rounded-2 border h-100">
                    <span class="d-block small fw-bold text-info"><i class="fa-solid fa-volume-high me-1"></i> Clarity:</span>
                    <span class="small text-secondary">${escapeHtml(evalData.clarity)}</span>
                  </div>
                </div>
              ` : ""}
              ${evalData.structure ? `
                <div class="col-12 col-md-4">
                  <div class="bg-white p-2 rounded-2 border h-100">
                    <span class="d-block small fw-bold text-primary"><i class="fa-solid fa-sitemap me-1"></i> Structure:</span>
                    <span class="small text-secondary">${escapeHtml(evalData.structure)}</span>
                  </div>
                </div>
              ` : ""}
              ${evalData.relevance ? `
                <div class="col-12 col-md-4">
                  <div class="bg-white p-2 rounded-2 border h-100">
                    <span class="d-block small fw-bold text-success"><i class="fa-solid fa-bullseye me-1"></i> Relevance:</span>
                    <span class="small text-secondary">${escapeHtml(evalData.relevance)}</span>
                  </div>
                </div>
              ` : ""}
            </div>
            ${evalData.tip ? `
              <div class="p-2 bg-warning-subtle rounded-2 border border-warning-subtle text-dark small d-flex align-items-start gap-2">
                <i class="fa-solid fa-lightbulb text-warning fs-6 mt-1 flex-shrink-0"></i>
                <div>
                  <strong>Key Improvement Tip:</strong> ${escapeHtml(evalData.tip)}
                </div>
              </div>
            ` : ""}
          </div>
        `;
      }

      // Side-by-side retry comparison card (#467)
      let comparisonHtml = "";
      if (result.comparison && result.comparison.criteria) {
        const comp = result.comparison;
        const ov = comp.overall || {};
        let ovBadge = "";
        if (ov.status === "improved") {
          ovBadge = `<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill"><i class="fa-solid fa-arrow-trend-up me-1"></i> Overall: +${ov.diff} pts</span>`;
        } else if (ov.status === "declined") {
          ovBadge = `<span class="badge bg-danger-subtle text-danger border border-danger-subtle rounded-pill"><i class="fa-solid fa-arrow-trend-down me-1"></i> Overall: ${ov.diff} pts</span>`;
        } else {
          ovBadge = `<span class="badge bg-secondary-subtle text-secondary border rounded-pill"><i class="fa-solid fa-equals me-1"></i> Overall: Unchanged</span>`;
        }

        let critCols = "";
        for (const [ckey, cinfo] of Object.entries(comp.criteria)) {
          const diffSign = cinfo.diff > 0 ? `+${cinfo.diff}` : `${cinfo.diff}`;
          let diffBadge = "";
          if (cinfo.diff > 0) {
            diffBadge = `<span class="badge bg-success-subtle text-success ms-1 small">${diffSign}</span>`;
          } else if (cinfo.diff < 0) {
            diffBadge = `<span class="badge bg-danger-subtle text-danger ms-1 small">${diffSign}</span>`;
          } else {
            diffBadge = `<span class="badge bg-secondary-subtle text-secondary ms-1 small">0</span>`;
          }

          critCols += `
            <div class="col-6 col-md-3">
              <div class="bg-white p-2 rounded-2 border text-center h-100">
                <span class="d-block small text-muted">${escapeHtml(cinfo.label || ckey)}</span>
                <span class="fw-bold">${cinfo.current_score}/100</span>
                ${diffBadge}
              </div>
            </div>
          `;
        }

        let addressedHtml = "";
        if (comp.addressed_points && comp.addressed_points.length > 0) {
          addressedHtml = `
            <div class="small text-success mb-1 mt-2">
              <b><i class="fa-solid fa-check-circle me-1"></i> Addressed Feedback:</b>
              <ul class="mb-0 ps-3">
                ${comp.addressed_points.map(pt => `<li>${escapeHtml(pt)}</li>`).join("")}
              </ul>
            </div>
          `;
        }

        let unaddressedHtml = "";
        if (comp.unaddressed_points && comp.unaddressed_points.length > 0) {
          unaddressedHtml = `
            <div class="small text-danger mb-0 mt-2">
              <b><i class="fa-solid fa-triangle-exclamation me-1"></i> Focus Areas:</b>
              <ul class="mb-0 ps-3">
                ${comp.unaddressed_points.map(pt => `<li>${escapeHtml(pt)}</li>`).join("")}
              </ul>
            </div>
          `;
        }

        comparisonHtml = `
          <div class="card border rounded-3 p-3 my-2 bg-light retry-comparison-card shadow-xs">
            <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-1">
              <span class="small fw-bold text-dark"><i class="fa-solid fa-code-compare text-primary me-1"></i> Attempt Comparison (Attempt ${result.attempt_number || 2} vs Attempt ${result.attempt_number ? result.attempt_number - 1 : 1}):</span>
              ${ovBadge}
            </div>
            <div class="row g-2 mb-1">
              ${critCols}
            </div>
            ${addressedHtml}
            ${unaddressedHtml}
          </div>
        `;
      }

      // Retry Action Button (#467)
      let retryBarHtml = "";
      const retriesLeft = typeof result.retries_left === "number" ? result.retries_left : (2 - (result.retry_count || 0));
      if (!result.completed && retriesLeft > 0) {
        retryBarHtml = `
          <div class="mt-3 pt-2 border-top d-flex justify-content-between align-items-center flex-wrap gap-2 retry-action-bar">
            <button type="button" class="btn btn-sm btn-outline-primary rounded-pill px-3 btn-try-again" data-question-index="${questionIndex}" data-retries-left="${retriesLeft}">
              <i class="fa-solid fa-rotate-left me-1"></i> Try Again (${retriesLeft} ${retriesLeft === 1 ? 'retry' : 'retries'} left)
            </button>
            <span class="small text-muted">Incorporate the feedback above and refine your response.</span>
          </div>
        `;
      } else if (!result.completed && (result.retry_count || 0) >= 2) {
        retryBarHtml = `
          <div class="mt-3 pt-2 border-top d-flex justify-content-between align-items-center">
            <span class="badge bg-secondary-subtle text-secondary border rounded-pill px-3 py-1 small">
              <i class="fa-solid fa-ban me-1"></i> Max retries reached (2/2)
            </span>
          </div>
        `;
      }

      const feedbackText = `
        <div class="d-flex justify-content-between align-items-center mb-2 pb-1 border-bottom">
          <span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-3 py-1">
            <i class="fa-solid fa-clipboard-check me-1"></i> AI Feedback &amp; Analysis
          </span>
          ${timingBadgeHtml}
        </div>
        <div class="mb-2 lh-base"><b>Feedback:</b> ${evalData.feedback}</div>
        <div class="row g-2 mt-2 mb-2">
          <div class="col-sm-4"><span class="badge bg-primary-subtle text-primary border border-primary-subtle w-100 py-1">Tech: ${evalData.technical_accuracy}/100</span></div>
          <div class="col-sm-4"><span class="badge bg-success-subtle text-success border border-success-subtle w-100 py-1">Comm: ${evalData.communication_score}/100</span></div>
          <div class="col-sm-4"><span class="badge bg-info-subtle text-info border border-info-subtle w-100 py-1">Verbal Clarity: ${verbalClarity}/100</span></div>
        </div>
        ${fillersHtml}
        ${starHtml}
        ${probingFollowUpHtml}
        ${perAnswerFeedbackHtml}
        ${comparisonHtml}
        <b>Suggestions:</b><br/>
        <ul class="mb-0 mt-1 list-unstyled">
          ${(evalData.suggestions || []).map(s => `
            <li class="mb-1 p-2 bg-white rounded-3 border d-flex justify-content-between align-items-center gap-2">
              <span class="small text-dark">${escapeHtml(s)}</span>
              <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill py-0 px-2 flex-shrink-0 btn-copy-suggestion" data-copy-text="${escapeHtml(s)}" title="Copy suggestion">
                <i class="fa-regular fa-copy"></i>
              </button>
            </li>
          `).join("")}
        </ul>
        ${retryBarHtml}
      `;
      appendChatBubble(feedbackText, "evaluation");

      if (result.is_retry) {
        // Update all retry buttons and action bars for this question in the DOM
        const qIdxStr = String(questionIndex);
        const newRetriesLeft = typeof result.retries_left === "number" ? result.retries_left : 0;
        document.querySelectorAll(`.btn-try-again[data-question-index="${qIdxStr}"]`).forEach((b) => {
          b.setAttribute("data-retries-left", String(newRetriesLeft));
          if (newRetriesLeft <= 0) {
            const bar = b.closest(".retry-action-bar");
            if (bar) {
              bar.innerHTML = `
                <span class="badge bg-secondary-subtle text-secondary border rounded-pill px-3 py-1 small">
                  <i class="fa-solid fa-ban me-1"></i> Max retries reached (2/2)
                </span>
              `;
            }
          } else {
            b.innerHTML = `<i class="fa-solid fa-rotate-left me-1"></i> Try Again (${newRetriesLeft} ${newRetriesLeft === 1 ? 'retry' : 'retries'} left)`;
          }
        });

        // Restore active question index to next pending question if applicable
        const prevIndex = chatForm.getAttribute("data-previous-active-index");
        if (prevIndex !== null && !result.completed) {
          chatForm.setAttribute("data-question-index", prevIndex);
          chatForm.removeAttribute("data-previous-active-index");
        } else if (result.next_index !== undefined && !result.completed) {
          chatForm.setAttribute("data-question-index", String(result.next_index));
        }

        resetInputs();
        if (typeof showToast === "function") {
          showToast(`Retry evaluation recorded (Attempt ${result.attempt_number || 2}). See comparison above.`);
        }
      } else if (result.completed) {
        stopQuestionTimer();
        clearAllDraftsForThisSession();
        if (interviewTimerBar) {
          interviewTimerBar.classList.add("d-none");
        }
        let completionSummaryHtml = "<b>Congratulations! You have completed all mock interview questions.</b><br/>Please review your performance summary and export your transcript.";
        if (result.summary && (result.summary.strengths?.length || result.summary.weak_areas?.length)) {
          const strengths = result.summary.strengths || [];
          const weakAreas = result.summary.weak_areas || result.summary.improvements || [];
          completionSummaryHtml += `
            <div class="card border rounded-3 p-3 my-3 bg-white text-start shadow-xs">
              <h6 class="fw-bold text-dark mb-2"><i class="fa-solid fa-award text-primary me-2"></i>Performance Summary: Strengths &amp; Targeted Focus Areas</h6>
              <div class="row g-3">
                <div class="col-md-6">
                  <span class="small fw-bold text-success d-block mb-1"><i class="fa-solid fa-circle-check me-1"></i>Key Strengths:</span>
                  <ul class="small ps-3 text-secondary mb-0">
                    ${strengths.map(s => `<li>${escapeHtml(s)}</li>`).join("")}
                  </ul>
                </div>
                <div class="col-md-6 border-start-md">
                  <span class="small fw-bold text-danger d-block mb-1"><i class="fa-solid fa-triangle-exclamation me-1"></i>Areas for Improvement (Weak Areas):</span>
                  <ul class="small ps-3 text-secondary mb-0">
                    ${weakAreas.map(w => `<li>${escapeHtml(w)}</li>`).join("")}
                  </ul>
                </div>
              </div>
            </div>
          `;
        }
        appendChatBubble(completionSummaryHtml, "agent");
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
            <div class="d-flex justify-content-between align-items-center mb-2 pb-1 border-bottom">
              <span class="badge bg-primary text-white rounded-pill px-3 py-1 shadow-sm">
                <i class="fa-solid fa-play me-1"></i> Active Question ${nextQ.index + 1} &bull; ${nextQ.type}
              </span>
              <div class="d-flex align-items-center gap-1">
                <button type="button" class="btn btn-sm btn-outline-warning btn-bookmark-interview-q py-0 px-2 rounded-pill" title="Bookmark question" aria-label="Bookmark question" data-question-id="q-${nextQ.index}" data-question="${nextQ.question.replace(/"/g, '&quot;')}" data-category="${nextQ.type || 'Technical'}">
                  <i class="fa-regular fa-bookmark"></i> <span class="d-none d-sm-inline">Save</span>
                </button>
                <button type="button" class="btn btn-sm btn-outline-primary btn-tts py-0 px-2 rounded-pill" title="Read question aloud" data-tts="${nextQ.question.replace(/"/g, '&quot;')}">
                  <i class="fa-solid fa-volume-high me-1"></i> Listen
                </button>
              </div>
            </div>
            <div class="fw-semibold text-dark fs-6 lh-base">${nextQ.question}</div>
          `;
          const newBubble = appendChatBubble(nextBubbleHtml, "question");
          chatForm.setAttribute("data-question-index", nextQ.index);
          chatForm.setAttribute("data-question-type", nextQ.type || "Technical");
          resetInputs();
          restoreCurrentDraft();

          // Start timer for next question if timed mode is enabled (#431)
          if (isTimedMode) {
            startQuestionTimer(nextQ.type || "Technical");
          }

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
    bubble.setAttribute("role", "article");
    bubble.innerHTML = text;
    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Announce to screen readers via live region
    const announcer = document.getElementById("interviewLiveAnnouncer");
    if (announcer) {
      const tempDiv = document.createElement("div");
      tempDiv.innerHTML = text;
      const plainText = (tempDiv.textContent || tempDiv.innerText || "").replace(/\s+/g, " ").trim();
      const prefix = sender === "user" ? "Your answer submitted: " : (sender === "question" ? "New question: " : "Agent feedback: ");
      announcer.textContent = prefix + plainText;
    }

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

    // Render Behavioral STAR Story Breakdown Card
    const starEval = evaluation.star_evaluation || (evaluation.star_method_analysis ? {
      star_score: evaluation.star_score || 75,
      situation: { present: evaluation.star_method_analysis.situation_present ?? true, score: 75, excerpt: "" },
      task: { present: evaluation.star_method_analysis.task_present ?? true, score: 75, excerpt: "" },
      action: { present: evaluation.star_method_analysis.action_present ?? true, score: 80, excerpt: "" },
      result: { present: evaluation.star_method_analysis.result_present ?? true, score: 70, excerpt: "" },
      non_verbal_composure: { eye_contact_score: 85, eye_contact_status: "Good Focus", composure_score: 85, composure_rating: "Confident" },
      coaching: { suggested_star_rewrite: evaluation.star_method_analysis.feedback || "" },
    } : null);

    if (starEval) {
      const starCard = document.getElementById("starBreakdownCard");
      if (starCard) starCard.classList.remove("d-none");

      const overallBadge = document.getElementById("starOverallScoreBadge");
      if (overallBadge) {
        const sScore = starEval.star_score ?? 75;
        overallBadge.textContent = `STAR: ${sScore}/100`;
        overallBadge.className = `badge rounded-pill px-2 py-1 small ${sScore >= 75 ? "bg-success" : (sScore >= 50 ? "bg-warning text-dark" : "bg-danger")}`;
      }

      function updateStarPill(prefix, dataBlock) {
        const pill = document.getElementById(`pill${prefix}`);
        const scoreEl = document.getElementById(`score${prefix}`);
        const excerptEl = document.getElementById(`excerpt${prefix}`);
        if (!pill || !scoreEl) return;

        const score = dataBlock ? (dataBlock.score ?? 50) : 50;
        const present = dataBlock ? dataBlock.present : false;
        scoreEl.textContent = `${score}%`;

        pill.classList.remove("passed", "needs-work", "missing");
        if (score >= 75 && present) {
          pill.classList.add("passed");
        } else if (score >= 50) {
          pill.classList.add("needs-work");
        } else {
          pill.classList.add("missing");
        }

        if (excerptEl && dataBlock) {
          excerptEl.textContent = dataBlock.excerpt || dataBlock.feedback || "Identified";
          excerptEl.title = dataBlock.feedback || "";
        }
      }

      updateStarPill("Situation", starEval.situation);
      updateStarPill("Task", starEval.task);
      updateStarPill("Action", starEval.action);
      updateStarPill("Result", starEval.result);

      // Non-verbal telemetry summary
      const starEye = document.getElementById("starEyeSummary");
      const starComp = document.getElementById("starComposureSummary");
      const nv = starEval.non_verbal_composure || {};
      if (starEye) {
        const eScore = nv.eye_contact_score ?? 85;
        starEye.textContent = `${eScore}% (${nv.eye_contact_status || (eScore >= 75 ? "Good Focus" : "Intermittent")})`;
      }
      if (starComp) {
        const cScore = nv.composure_score ?? 85;
        starComp.textContent = `${cScore}% (${nv.composure_rating || (cScore >= 75 ? "Steady" : "Moderate")})`;
      }

      // Model STAR Rewrite
      const rewriteText = document.getElementById("starModelRewriteText");
      if (rewriteText && starEval.coaching && starEval.coaching.suggested_star_rewrite) {
        rewriteText.textContent = starEval.coaching.suggested_star_rewrite;
      }
    }

    // Progress updates
    const totalQuestions = parseInt(chatForm.getAttribute("data-total-questions")) || 15;
    const progPercent = totalQuestions > 0 ? Math.round((totalAnswered / totalQuestions) * 100) : 0;
    const progressTextEl = document.getElementById("interviewProgressText");
    const progressBarEl = document.getElementById("interviewProgressBar");
    if (progressTextEl) progressTextEl.innerText = `${totalAnswered}/${totalQuestions} Questions Answered (${progPercent}%)`;
    if (progressBarEl) progressBarEl.style.width = `${progPercent}%`;

    // Timing indicator badge (#431)
    const evalTimingBadge = document.getElementById("evalTimingBadge");
    const evalTimingText = document.getElementById("evalTimingText");
    const timeDisplay = evaluation.time_display || "";
    if (evalTimingBadge && evalTimingText) {
      if (timeDisplay) {
        evalTimingText.innerText = timeDisplay.charAt(0).toUpperCase() + timeDisplay.slice(1);
        evalTimingBadge.classList.remove("d-none");
      } else {
        evalTimingBadge.classList.add("d-none");
      }
    }

    // Enable Download Transcript buttons after at least one answer has been submitted (#161)
    if (totalAnswered > 0) {
      enableDownloadTranscriptButtons();
    }
  }

  function enableDownloadTranscriptButtons() {
    const btnDownload = document.getElementById("btnDownloadTranscript");
    if (btnDownload) {
      btnDownload.classList.remove("disabled");
      btnDownload.removeAttribute("aria-disabled");
      btnDownload.removeAttribute("tabindex");
    }
    const btnDropdown = document.getElementById("btnDownloadTranscriptDropdown");
    if (btnDropdown) {
      btnDropdown.classList.remove("disabled");
      btnDropdown.removeAttribute("disabled");
      btnDropdown.removeAttribute("aria-disabled");
    }
    const sideBtn = document.getElementById("sideBtnDownloadTranscript");
    if (sideBtn) {
      sideBtn.classList.remove("d-none");
    }
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

    // Display Timed Mode Pacing Metrics in Modal if available (#431)
    const modalTimingStatsCard = document.getElementById("modalTimingStatsCard");
    const modalTimedCount = document.getElementById("modalTimedCount");
    const modalAvgAnswerTime = document.getElementById("modalAvgAnswerTime");
    const modalWithinLimitRate = document.getElementById("modalWithinLimitRate");

    if (summary.timing_summary && summary.timing_summary.total_timed_questions > 0 && modalTimingStatsCard) {
      modalTimingStatsCard.classList.remove("d-none");
      if (modalTimedCount) modalTimedCount.innerText = `${summary.timing_summary.total_timed_questions}`;
      if (modalAvgAnswerTime) modalAvgAnswerTime.innerText = `${summary.timing_summary.formatted_avg_time || "--"}`;
      if (modalWithinLimitRate) modalWithinLimitRate.innerText = `${summary.timing_summary.within_limit_percentage}%`;
    } else if (modalTimingStatsCard) {
      modalTimingStatsCard.classList.add("d-none");
    }

    // Populate Comprehensive Competency Breakdown (#267)
    const compBreakdown = summary.competency_breakdown || {};
    const comps = compBreakdown.competencies || {};

    const bTechScore = document.getElementById("breakdownTechScore");
    const bTechRating = document.getElementById("breakdownTechRating");
    const bCommScore = document.getElementById("breakdownCommScore");
    const bCommRating = document.getElementById("breakdownCommRating");
    const bProbScore = document.getElementById("breakdownProbScore");
    const bProbRating = document.getElementById("breakdownProbRating");
    const bRelScore = document.getElementById("breakdownRelScore");
    const bRelRating = document.getElementById("breakdownRelRating");

    if (bTechScore && comps["Technical Knowledge"]) {
      bTechScore.innerText = `${comps["Technical Knowledge"].score}%`;
      if (bTechRating) bTechRating.innerText = comps["Technical Knowledge"].rating;
    }
    if (bCommScore && comps["Communication"]) {
      bCommScore.innerText = `${comps["Communication"].score}%`;
      if (bCommRating) bCommRating.innerText = comps["Communication"].rating;
    }
    if (bProbScore && comps["Problem-Solving"]) {
      bProbScore.innerText = `${comps["Problem-Solving"].score}%`;
      if (bProbRating) bProbRating.innerText = comps["Problem-Solving"].rating;
    }
    if (bRelScore && comps["Answer Relevance"]) {
      bRelScore.innerText = `${comps["Answer Relevance"].score}%`;
      if (bRelRating) bRelRating.innerText = comps["Answer Relevance"].rating;
    }

    const strengthsList = document.getElementById("modalStrengthsList");
    const resolvedStrengths = summary.strengths?.length ? summary.strengths : compBreakdown.strengths;
    if (strengthsList && resolvedStrengths?.length) {
      strengthsList.innerHTML = resolvedStrengths.map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    }
    const improvementsList = document.getElementById("modalImprovementsList");
    const resolvedImprovements = summary.weak_areas?.length ? summary.weak_areas : (summary.improvements?.length ? summary.improvements : compBreakdown.improvements);
    if (improvementsList && resolvedImprovements?.length) {
      improvementsList.innerHTML = resolvedImprovements.map((i) => `<li>${escapeHtml(i)}</li>`).join("");
    }

    const bsModal = new bootstrap.Modal(modalEl);
    bsModal.show();
  }
}

/**
 * Enables copying single-week roadmap tasks and exporting the complete 6-week
 * preparation schedule as a structured Markdown file for study notes or Notion.
 */


// Auto-initialize when loaded on interview pages
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initInterviewDraftLogoutCleanup();
      initMockInterview();
    });
  } else {
    initInterviewDraftLogoutCleanup();
    initMockInterview();
  }
}
