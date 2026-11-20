/**
 * Project Deep Dive Module (static/js/modules/project_deep_dive.js)
 * ===============================================================
 * Architecture defense simulator and deep-dive technical follow-up questions (#466).
 */

import { escapeHtml, showToast, getCsrfToken } from "./utils.js";

export function initProjectDeepDive() {
  const pDataStore = document.getElementById("projectsDataStore");
  if (!pDataStore) return;

  const mainContainer = document.getElementById("main-content");
  const analysisId = mainContainer ? mainContainer.getAttribute("data-analysis-id") : "";
  const companyName = mainContainer ? mainContainer.getAttribute("data-company-name") : "Placement";

  let rawProjects = [];
  try {
    rawProjects = JSON.parse(pDataStore.getAttribute("data-projects") || "[]");
  } catch (err) {
    rawProjects = [];
  }

  // DOM Elements
  const projectSelectionView = document.getElementById("projectSelectionView");
  const simulatorView = document.getElementById("projectDeepDiveSimulatorView");
  const activeProjectTitle = document.getElementById("activeProjectTitle");
  const activeProjectTechStack = document.getElementById("activeProjectTechStack");
  const activeProjectDescription = document.getElementById("activeProjectDescription");
  const projectContextDrawer = document.getElementById("projectContextDrawer");
  const btnToggleProjectContext = document.getElementById("btnToggleProjectContext");
  const btnChangeProject = document.getElementById("btnChangeProject");

  const questionProgressText = document.getElementById("questionProgressText");
  const activeCategoryBadge = document.getElementById("activeCategoryBadge");
  const progressBar = document.getElementById("progressBar");
  const activeQuestionText = document.getElementById("activeQuestionText");
  const btnTtsQuestion = document.getElementById("btnTtsQuestion");

  const answerForm = document.getElementById("projectAnswerForm");
  const answerInput = document.getElementById("projectAnswerInput");
  const answerWordCount = document.getElementById("answerWordCount");
  const btnSubmitAnswer = document.getElementById("btnSubmitProjectAnswer");

  const answerEvalCard = document.getElementById("answerEvaluationCard");
  const evalOverallScoreBadge = document.getElementById("evalOverallScoreBadge");
  const evalClarityScore = document.getElementById("evalClarityScore");
  const evalDepthScore = document.getElementById("evalDepthScore");
  const evalConsistencyScore = document.getElementById("evalConsistencyScore");
  const evalTipText = document.getElementById("evalTipText");
  const evalFeedbackText = document.getElementById("evalFeedbackText");
  const btnNextQuestion = document.getElementById("btnNextQuestion");

  // Modals
  const thinProjectModalEl = document.getElementById("thinProjectModal");
  const customProjectModalEl = document.getElementById("customProjectModal");
  const summaryModalEl = document.getElementById("deepDiveSummaryModal");

  // State
  let activeProject = null;
  let activeQuestions = [];
  let currentQuestionIndex = 0;
  let evaluationsHistory = [];
  let pendingThinProject = null;

  function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  }

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  const categoryLabels = {
    "design_choices": "Design Choices",
    "challenges": "Challenges & Bugs",
    "testing": "Testing & Verification",
    "improvements": "Retrospective & Polish",
    "tradeoffs": "Technical Trade-offs"
  };

  // 1. Project selection handlers
  document.querySelectorAll(".btn-select-project").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = btn.getAttribute("data-project-id");
      const proj = rawProjects.find((p) => String(p.id) === String(pid));
      if (proj) {
        startProjectDeepDive(proj);
      }
    });
  });

  // 2. Thin project selection handler
  document.querySelectorAll(".btn-select-thin-project").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = btn.getAttribute("data-project-id");
      const proj = rawProjects.find((p) => String(p.id) === String(pid));
      if (proj && thinProjectModalEl) {
        pendingThinProject = proj;
        document.getElementById("modalProjectTitle").value = proj.title || "";
        document.getElementById("modalProjectTech").value = proj.tech_stack || "";
        document.getElementById("modalProjectAdditionalDetails").value = "";
        const modal = new bootstrap.Modal(thinProjectModalEl);
        modal.show();
      }
    });
  });

  const btnConfirmStartWithDetails = document.getElementById("btnConfirmStartWithDetails");
  if (btnConfirmStartWithDetails) {
    btnConfirmStartWithDetails.addEventListener("click", () => {
      if (!pendingThinProject) return;
      const extraTech = document.getElementById("modalProjectTech")?.value.trim() || "";
      const extraDetails = document.getElementById("modalProjectAdditionalDetails")?.value.trim() || "";

      const updatedProj = { ...pendingThinProject };
      if (extraTech) updatedProj.tech_stack = extraTech;
      
      const modalInstance = bootstrap.Modal.getInstance(thinProjectModalEl);
      if (modalInstance) modalInstance.hide();

      startProjectDeepDive(updatedProj, extraDetails);
    });
  }

  // 3. Custom project creation handler (when resume has no projects)
  const btnOpenCustomModal = document.getElementById("btnOpenCustomProjectModal");
  if (btnOpenCustomModal && customProjectModalEl) {
    btnOpenCustomModal.addEventListener("click", () => {
      const modal = new bootstrap.Modal(customProjectModalEl);
      modal.show();
    });
  }

  const btnSaveCustomProject = document.getElementById("btnSaveCustomProject");
  if (btnSaveCustomProject) {
    btnSaveCustomProject.addEventListener("click", () => {
      const title = document.getElementById("customProjectTitle")?.value.trim() || "";
      const tech = document.getElementById("customProjectTech")?.value.trim() || "";
      const desc = document.getElementById("customProjectDesc")?.value.trim() || "";

      if (!title || !desc) {
        if (typeof showToast === "function") showToast("Please provide both a project title and description.");
        return;
      }

      const customProj = {
        id: "custom-" + Date.now(),
        title: title,
        tech_stack: tech,
        description: desc,
        short_description: desc.slice(0, 150),
        is_thin: false,
        word_count: desc.split(/\s+/).length
      };

      const modalInstance = bootstrap.Modal.getInstance(customProjectModalEl);
      if (modalInstance) modalInstance.hide();

      startProjectDeepDive(customProj);
    });
  }

  // 4. Start Deep-Dive Session
  async function startProjectDeepDive(project, additionalDetails = "") {
    activeProject = project;
    currentQuestionIndex = 0;
    evaluationsHistory = [];

    // Switch views
    if (projectSelectionView) projectSelectionView.classList.add("d-none");
    if (simulatorView) simulatorView.classList.remove("d-none");

    // Populate active project headers
    if (activeProjectTitle) activeProjectTitle.textContent = project.title || "Project";
    if (activeProjectTechStack) activeProjectTechStack.textContent = project.tech_stack ? `Tech Stack: ${project.tech_stack}` : "Tech Stack: Stated on resume";
    if (activeProjectDescription) activeProjectDescription.textContent = project.description || "No project description provided.";

    // Show loading on question card
    if (activeQuestionText) {
      activeQuestionText.innerHTML = '<span class="spinner-border spinner-border-sm text-primary me-2" role="status"></span> Generating 5 grounded technical follow-up questions...';
    }
    if (answerForm) answerForm.classList.add("d-none");
    if (answerEvalCard) answerEvalCard.classList.add("d-none");

    try {
      const resp = await fetch(`/api/interview/${analysisId}/project-deep-dive/questions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          project: project,
          additional_details: additionalDetails
        })
      });

      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.error || "Failed to generate project questions.");
      }

      activeQuestions = data.questions || [];
      if (activeQuestions.length === 0) {
        throw new Error("No questions were generated for this project.");
      }

      renderQuestion(0);
    } catch (err) {
      if (activeQuestionText) {
        activeQuestionText.innerHTML = `<span class="text-danger"><i class="fa-solid fa-triangle-exclamation me-1"></i> ${escapeHtml(err.message)}</span>`;
      }
      if (typeof showToast === "function") {
        showToast(err.message);
      }
    }
  }

  // 5. Render Question
  function renderQuestion(qIndex) {
    if (!activeQuestions[qIndex]) return;
    const q = activeQuestions[qIndex];
    currentQuestionIndex = qIndex;

    const total = activeQuestions.length;
    const pct = Math.round(((qIndex + 1) / total) * 100);

    if (questionProgressText) questionProgressText.textContent = `Question ${qIndex + 1} of ${total}`;
    if (progressBar) {
      progressBar.style.width = `${pct}%`;
      progressBar.setAttribute("aria-valuenow", String(pct));
    }
    if (activeCategoryBadge) {
      activeCategoryBadge.textContent = categoryLabels[q.category] || q.category || "Technical Rationale";
    }

    if (activeQuestionText) {
      activeQuestionText.textContent = q.question;
    }

    // Reset and show answer input
    if (answerInput) {
      answerInput.value = "";
      answerInput.disabled = false;
      answerInput.focus();
    }
    if (answerWordCount) answerWordCount.textContent = "0 words";
    if (btnSubmitAnswer) {
      btnSubmitAnswer.disabled = false;
      btnSubmitAnswer.innerHTML = '<i class="fa-solid fa-paper-plane me-1"></i> Submit Answer';
    }

    if (answerForm) answerForm.classList.remove("d-none");
    if (answerEvalCard) answerEvalCard.classList.add("d-none");
  }

  // 6. Word counter & Keyboard shortcut on answer input
  if (answerInput) {
    answerInput.addEventListener("input", () => {
      const words = answerInput.value.trim().split(/\s+/).filter(Boolean);
      if (answerWordCount) answerWordCount.textContent = `${words.length} words`;
    });

    answerInput.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (answerInput.value.trim() && !btnSubmitAnswer.disabled) {
          answerForm.requestSubmit();
        }
      }
    });
  }

  // 7. Toggle context drawer
  if (btnToggleProjectContext && projectContextDrawer) {
    btnToggleProjectContext.addEventListener("click", () => {
      const bsCollapse = bootstrap.Collapse.getOrCreateInstance(projectContextDrawer);
      bsCollapse.toggle();
    });
  }

  // 8. Change Project button
  if (btnChangeProject) {
    btnChangeProject.addEventListener("click", () => {
      if (simulatorView) simulatorView.classList.add("d-none");
      if (projectSelectionView) projectSelectionView.classList.remove("d-none");
    });
  }

  // 9. Audio TTS on question
  if (btnTtsQuestion) {
    btnTtsQuestion.addEventListener("click", () => {
      if (!("speechSynthesis" in window)) {
        if (typeof showToast === "function") showToast("Speech synthesis not supported in this browser.");
        return;
      }
      const textToSpeak = activeQuestionText ? activeQuestionText.textContent : "";
      if (!textToSpeak) return;

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(textToSpeak);
      utterance.rate = 1.0;
      btnTtsQuestion.classList.add("btn-primary");
      btnTtsQuestion.classList.remove("btn-outline-primary");
      utterance.onend = () => {
        btnTtsQuestion.classList.remove("btn-primary");
        btnTtsQuestion.classList.add("btn-outline-primary");
      };
      window.speechSynthesis.speak(utterance);
    });
  }

  // 10. Submit Answer & Evaluate
  if (answerForm) {
    answerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const ans = answerInput ? answerInput.value.trim() : "";
      if (!ans) return;

      if (btnSubmitAnswer) {
        btnSubmitAnswer.disabled = true;
        btnSubmitAnswer.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Evaluating Technical Defense...';
      }
      if (answerInput) answerInput.disabled = true;

      const currentQ = activeQuestions[currentQuestionIndex];

      try {
        const resp = await fetch(`/api/interview/${analysisId}/project-deep-dive/evaluate`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken()
          },
          body: JSON.stringify({
            project: activeProject,
            question: currentQ.question,
            question_index: currentQuestionIndex,
            answer: ans
          })
        });

        const data = await resp.json();
        if (!resp.ok || !data.success) {
          throw new Error(data.error || "Evaluation failed.");
        }

        const ev = data.evaluation || {};
        evaluationsHistory.push(ev);

        // Populate Evaluation Card
        if (evalOverallScoreBadge) {
          const ov = ev.overall_score || 0;
          evalOverallScoreBadge.textContent = `${ov} / 100`;
          evalOverallScoreBadge.className = `badge border rounded-pill px-3 py-1 fw-bold fs-6 ${ov >= 75 ? "bg-success-subtle text-success border-success-subtle" : (ov >= 50 ? "bg-warning-subtle text-dark border-warning-subtle" : "bg-danger-subtle text-danger border-danger-subtle")}`;
        }
        if (evalClarityScore) evalClarityScore.textContent = `${ev.clarity_score || 0}%`;
        if (evalDepthScore) evalDepthScore.textContent = `${ev.depth_score || 0}%`;
        if (evalConsistencyScore) evalConsistencyScore.textContent = `${ev.consistency_score || 0}%`;
        if (evalTipText) evalTipText.textContent = ev.tip || "Quantify the technical impact and trade-offs of your choices.";
        if (evalFeedbackText) evalFeedbackText.textContent = ev.feedback || "Answer evaluated against your project scope.";

        // Update Next button label
        if (btnNextQuestion) {
          if (currentQuestionIndex + 1 < activeQuestions.length) {
            btnNextQuestion.innerHTML = 'Next Question <i class="fa-solid fa-arrow-right ms-1"></i>';
          } else {
            btnNextQuestion.innerHTML = 'Complete Deep-Dive &amp; View Summary <i class="fa-solid fa-award ms-1"></i>';
          }
        }

        if (answerForm) answerForm.classList.add("d-none");
        if (answerEvalCard) answerEvalCard.classList.remove("d-none");

      } catch (err) {
        if (btnSubmitAnswer) {
          btnSubmitAnswer.disabled = false;
          btnSubmitAnswer.innerHTML = '<i class="fa-solid fa-paper-plane me-1"></i> Submit Answer';
        }
        if (answerInput) answerInput.disabled = false;
        if (typeof showToast === "function") showToast(err.message);
      }
    });
  }

  // 11. Next Question Button
  if (btnNextQuestion) {
    btnNextQuestion.addEventListener("click", () => {
      if (currentQuestionIndex + 1 < activeQuestions.length) {
        renderQuestion(currentQuestionIndex + 1);
      } else {
        showCompletionSummary();
      }
    });
  }

  // 12. Show Completion Summary Modal
  function showCompletionSummary() {
    if (!summaryModalEl) return;

    let sumClarity = 0, sumDepth = 0, sumConsistency = 0, sumOverall = 0;
    const tips = [];

    evaluationsHistory.forEach((ev) => {
      sumClarity += ev.clarity_score || 0;
      sumDepth += ev.depth_score || 0;
      sumConsistency += ev.consistency_score || 0;
      sumOverall += ev.overall_score || 0;
      if (ev.tip) tips.push(ev.tip);
    });

    const cnt = Math.max(1, evaluationsHistory.length);
    const avgClarity = Math.round(sumClarity / cnt);
    const avgDepth = Math.round(sumDepth / cnt);
    const avgConsistency = Math.round(sumConsistency / cnt);
    const avgOverall = Math.round(sumOverall / cnt);

    const summaryOverallScore = document.getElementById("summaryOverallScore");
    const summaryReadinessBadge = document.getElementById("summaryReadinessBadge");
    const summaryAvgClarity = document.getElementById("summaryAvgClarity");
    const summaryAvgDepth = document.getElementById("summaryAvgDepth");
    const summaryAvgConsistency = document.getElementById("summaryAvgConsistency");
    const summaryTipsList = document.getElementById("summaryTipsList");

    if (summaryOverallScore) summaryOverallScore.textContent = `${avgOverall}% Overall Score`;
    if (summaryAvgClarity) summaryAvgClarity.textContent = `${avgClarity}%`;
    if (summaryAvgDepth) summaryAvgDepth.textContent = `${avgDepth}%`;
    if (summaryAvgConsistency) summaryAvgConsistency.textContent = `${avgConsistency}%`;

    if (summaryReadinessBadge) {
      if (avgOverall >= 80) {
        summaryReadinessBadge.textContent = "Placement Ready (Project Defense)";
        summaryReadinessBadge.className = "badge bg-success-subtle text-success border border-success-subtle rounded-pill px-4 py-2 fs-6 fw-bold mb-2";
      } else if (avgOverall >= 65) {
        summaryReadinessBadge.textContent = "Competent (Needs Targeted Polish)";
        summaryReadinessBadge.className = "badge bg-warning-subtle text-dark border border-warning-subtle rounded-pill px-4 py-2 fs-6 fw-bold mb-2";
      } else {
        summaryReadinessBadge.textContent = "Needs Comprehensive Preparation";
        summaryReadinessBadge.className = "badge bg-danger-subtle text-danger border border-danger-subtle rounded-pill px-4 py-2 fs-6 fw-bold mb-2";
      }
    }

    if (summaryTipsList) {
      summaryTipsList.innerHTML = tips.map((t) => `<li class="mb-1">${escapeHtml(t)}</li>`).join("");
    }

    const modal = new bootstrap.Modal(summaryModalEl);
    modal.show();
  }

  // 13. Restart / Practice Another Project
  const btnRestartAnother = document.getElementById("btnRestartAnotherProject");
  if (btnRestartAnother && summaryModalEl) {
    btnRestartAnother.addEventListener("click", () => {
      const modalInstance = bootstrap.Modal.getInstance(summaryModalEl);
      if (modalInstance) modalInstance.hide();
      if (simulatorView) simulatorView.classList.add("d-none");
      if (projectSelectionView) projectSelectionView.classList.remove("d-none");
    });
  }
}




if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initProjectDeepDive);
  } else {
    initProjectDeepDive();
  }
}
