/**
 * Bookmarks Module (static/js/modules/bookmarks.js)
 * ================================================
 * Question bookmarking for coding practice and interview preparation (#234, #268):
 * - Optimistic button UI toggle
 * - LocalStorage caching and server synchronization
 * - Saved questions counter and toast notifications
 */

import { escapeHtml, showToast } from "./utils.js";

export function initCodingBookmarks() {
  const page = document.querySelector(".coding-practice-page");
  if (!page) return;

  function showBookmarkToast(message, isSuccess = true) {
    const toastEl = document.getElementById("bookmarkToast");
    const toastMsg = document.getElementById("bookmarkToastMsg");
    const toastIcon = document.getElementById("bookmarkToastIcon");
    if (!toastEl || !toastMsg) return;

    toastMsg.textContent = message;
    if (toastIcon) {
      toastIcon.className = isSuccess
        ? "fa-solid fa-bookmark text-warning me-2 fs-5"
        : "fa-solid fa-circle-exclamation text-danger me-2 fs-5";
    }

    if (window.bootstrap && window.bootstrap.Toast) {
      const toast = window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2800 });
      toast.show();
    }
  }

  function updateSavedCount() {
    const countBadge = document.getElementById("savedQuestionsCountBadge");
    const headerSavedCount = document.querySelectorAll(".header-saved-count");
    const grid = document.getElementById("savedQuestionsGrid");
    const emptyMsg = document.getElementById("noSavedQuestionsMessage");

    let currentCount = 0;
    if (grid) {
      currentCount = grid.querySelectorAll(".saved-problem-item").length;
    }

    if (countBadge) {
      countBadge.textContent = String(currentCount);
    }
    headerSavedCount.forEach((el) => {
      el.textContent = String(currentCount);
    });

    if (currentCount === 0) {
      if (emptyMsg) emptyMsg.classList.remove("d-none");
      if (grid) grid.classList.add("d-none");
    } else {
      if (emptyMsg) emptyMsg.classList.add("d-none");
      if (grid) grid.classList.remove("d-none");
    }
  }

  function createSavedCardElement(prob) {
    const col = document.createElement("div");
    col.className = "col-md-6 saved-problem-item";
    col.id = `saved-card-${prob.id}`;

    const diffClass =
      prob.difficulty === "Easy"
        ? "bg-success"
        : prob.difficulty === "Medium"
        ? "bg-warning text-dark"
        : "bg-danger";

    const companiesHtml =
      Array.isArray(prob.companies) && prob.companies.length > 0
        ? `<div class="mb-3">
             <div class="small fw-semibold text-muted mb-1">Target Companies:</div>
             <div class="d-flex flex-wrap gap-1">
               ${prob.companies
                 .map((c) => `<span class="badge bg-light text-dark border rounded-pill small">${escapeHtml(c)}</span>`)
                 .join("")}
             </div>
           </div>`
        : "";

    const complexityHtml =
      prob.time_complexity || prob.space_complexity
        ? `<i class="fa-solid fa-clock me-1"></i> ${escapeHtml(prob.time_complexity || "O(N)")} | <i class="fa-solid fa-memory me-1"></i> ${escapeHtml(prob.space_complexity || "O(1)")}`
        : `<i class="fa-solid fa-bookmark text-warning me-1"></i> Saved Question`;

    col.innerHTML = `
      <div class="card border border-warning-subtle shadow-sm rounded-4 h-100 p-4 d-flex flex-column justify-content-between bg-white position-relative">
        <div>
          <div class="d-flex justify-content-between align-items-start mb-2">
            <div>
              <span class="badge ${diffClass} rounded-pill me-2">
                ${escapeHtml(prob.difficulty || "Medium")}
              </span>
              <span class="badge bg-secondary-subtle text-secondary rounded-pill">${escapeHtml(prob.topic || "DSA")}</span>
            </div>
            <button type="button" 
                    class="btn btn-sm btn-outline-danger btn-remove-bookmark rounded-circle p-2 d-inline-flex align-items-center justify-content-center"
                    data-problem-id="${escapeHtml(prob.id)}"
                    data-problem-title="${escapeHtml(prob.title)}"
                    title="Remove from Saved Questions"
                    aria-label="Remove ${escapeHtml(prob.title)} from Saved Questions"
                    style="width: 36px; height: 36px;">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </div>

          <h5 class="fw-bold text-dark mb-1">${escapeHtml(prob.title)}</h5>
          <p class="text-muted small mb-3">${escapeHtml(prob.description || "")}</p>
          ${companiesHtml}
        </div>

        <div class="pt-3 border-top d-flex flex-wrap justify-content-between align-items-center gap-2">
          <span class="small text-muted">
            ${complexityHtml}
          </span>
          <a href="${escapeHtml(prob.practice_url || "#")}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-primary btn-sm rounded-pill px-3">
            Solve on ${escapeHtml(prob.platform || "LeetCode")} <i class="fa-solid fa-arrow-up-right-from-square ms-1"></i>
          </a>
        </div>
      </div>
    `;

    return col;
  }

  // Handle bookmark button click and remove button click via delegated listener
  document.addEventListener("click", async (e) => {
    const bookmarkBtn = e.target.closest(".btn-bookmark-question");
    const removeBtn = e.target.closest(".btn-remove-bookmark");

    if (bookmarkBtn) {
      e.preventDefault();
      const problemId = bookmarkBtn.dataset.problemId;
      if (!problemId) return;

      const isCurrentlyActive = bookmarkBtn.classList.contains("active");
      const title = bookmarkBtn.dataset.problemTitle || "Coding Problem";
      const difficulty = bookmarkBtn.dataset.problemDifficulty || "Medium";
      const topic = bookmarkBtn.dataset.problemTopic || "DSA";
      const platform = bookmarkBtn.dataset.problemPlatform || "LeetCode";
      const practiceUrl = bookmarkBtn.dataset.problemUrl || "";
      const timeComp = bookmarkBtn.dataset.problemTime || "";
      const spaceComp = bookmarkBtn.dataset.problemSpace || "";
      const desc = bookmarkBtn.dataset.problemDescription || "";
      const companiesRaw = bookmarkBtn.dataset.problemCompanies || "";
      const companies = companiesRaw ? companiesRaw.split(",") : [];

      // Optimistic update on all matching buttons across the page
      const matchingBtns = document.querySelectorAll(`.btn-bookmark-question[data-problem-id="${CSS.escape(problemId)}"]`);
      const grid = document.getElementById("savedQuestionsGrid");

      if (isCurrentlyActive) {
        // Toggle off
        matchingBtns.forEach((btn) => {
          btn.classList.remove("active", "btn-warning", "text-dark");
          btn.classList.add("btn-outline-secondary");
          const icon = btn.querySelector("i");
          if (icon) icon.className = "fa-regular fa-bookmark";
          btn.title = "Save to Bookmarks";
          btn.setAttribute("aria-label", `Bookmark ${title}`);
        });

        const existingCard = document.getElementById(`saved-card-${problemId}`);
        if (existingCard) {
          existingCard.remove();
        }
        updateSavedCount();
        showBookmarkToast(`Removed "${title}" from saved questions.`);

        try {
          const res = await fetch(`/api/coding-practice/bookmark/${encodeURIComponent(problemId)}`, {
            method: "DELETE",
            headers: {
              "Accept": "application/json",
              "X-Requested-With": "XMLHttpRequest"
            }
          });
          const data = await res.json();
          if (!data.success) {
            console.warn("Server bookmark removal returned failure:", data);
          }
        } catch (err) {
          console.error("Failed to sync bookmark removal with server:", err);
          showBookmarkToast("Failed to sync removal with server.", false);
        }
      } else {
        // Toggle on
        matchingBtns.forEach((btn) => {
          btn.classList.add("active", "btn-warning", "text-dark");
          btn.classList.remove("btn-outline-secondary");
          const icon = btn.querySelector("i");
          if (icon) icon.className = "fa-solid fa-bookmark";
          btn.title = "Remove from Saved Questions";
          btn.setAttribute("aria-label", `Remove ${title} from Saved Questions`);
        });

        if (grid && !document.getElementById(`saved-card-${problemId}`)) {
          const probObj = {
            id: problemId,
            title: title,
            difficulty: difficulty,
            topic: topic,
            platform: platform,
            practice_url: practiceUrl,
            time_complexity: timeComp,
            space_complexity: spaceComp,
            description: desc,
            companies: companies
          };
          const cardEl = createSavedCardElement(probObj);
          grid.prepend(cardEl);
        }
        updateSavedCount();
        showBookmarkToast(`Saved "${title}" to your bookmarks!`);

        try {
          const res = await fetch("/api/coding-practice/bookmark", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json",
              "X-Requested-With": "XMLHttpRequest"
            },
            body: JSON.stringify({
              problem_id: problemId,
              title: title,
              difficulty: difficulty,
              topic: topic,
              platform: platform,
              practice_url: practiceUrl,
              time_complexity: timeComp,
              space_complexity: spaceComp,
              description: desc,
              companies: companies
            })
          });
          const data = await res.json();
          if (!data.success) {
            console.warn("Server bookmark save returned failure:", data);
          }
        } catch (err) {
          console.error("Failed to sync bookmark save with server:", err);
          showBookmarkToast("Saved locally, but server sync failed.", false);
        }
      }
    } else if (removeBtn) {
      e.preventDefault();
      const problemId = removeBtn.dataset.problemId;
      const title = removeBtn.dataset.problemTitle || "Coding Problem";
      if (!problemId) return;

      const card = document.getElementById(`saved-card-${problemId}`);
      if (card) {
        card.remove();
      }

      // Update matching button in recommended list if present
      const matchingBtns = document.querySelectorAll(`.btn-bookmark-question[data-problem-id="${CSS.escape(problemId)}"]`);
      matchingBtns.forEach((btn) => {
        btn.classList.remove("active", "btn-warning", "text-dark");
        btn.classList.add("btn-outline-secondary");
        const icon = btn.querySelector("i");
        if (icon) icon.className = "fa-regular fa-bookmark";
        btn.title = "Save to Bookmarks";
        btn.setAttribute("aria-label", `Bookmark ${title}`);
      });

      updateSavedCount();
      showBookmarkToast(`Removed "${title}" from saved questions.`);

      try {
        await fetch(`/api/coding-practice/bookmark/${encodeURIComponent(problemId)}`, {
          method: "DELETE",
          headers: {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest"
          }
        });
      } catch (err) {
        console.error("Failed to sync bookmark delete with server:", err);
      }
    }
  });

  // Initial count verification on load
  updateSavedCount();
}


/**
 * Interview Question Bookmarks (#358)
 * Enables students to bookmark questions during or after mock interviews.
 */
export function initInterviewBookmarks() {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".btn-bookmark-interview-q");
    if (!btn) return;

    e.preventDefault();
    const qId = btn.getAttribute("data-question-id") || "";
    const qText = btn.getAttribute("data-question") || "";
    const category = btn.getAttribute("data-category") || "Technical";
    const company = btn.getAttribute("data-company") || "General";

    if (!qText && !qId) return;

    const originalContent = btn.innerHTML;
    btn.disabled = true;

    try {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      const res = await fetch("/api/interview/bookmark/toggle", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          question_id: qId,
          question_text: qText,
          category: category,
          company_name: company
        })
      });

      const data = await res.json();
      btn.disabled = false;
      if (data.success) {
        if (data.bookmarked) {
          btn.classList.remove("btn-outline-warning");
          btn.classList.add("btn-warning", "text-dark");
          btn.innerHTML = '<i class="fa-solid fa-bookmark me-1"></i> <span class="d-none d-sm-inline">Saved</span>';
          btn.title = "Saved in your bookmarks";
        } else {
          btn.classList.remove("btn-warning", "text-dark");
          btn.classList.add("btn-outline-warning");
          btn.innerHTML = '<i class="fa-regular fa-bookmark me-1"></i> <span class="d-none d-sm-inline">Save</span>';
          btn.title = "Bookmark question";
        }
      } else {
        btn.innerHTML = originalContent;
      }
    } catch (err) {
      console.error("Error toggling interview bookmark:", err);
      btn.disabled = false;
      btn.innerHTML = originalContent;
    }
  });
}


/**
 * Daily Preparation Streak Tracker (#236)
 * Handles interactive monthly calendar navigation, AJAX rendering of active preparation days,
 * and live updates for consistency tracking.
 */


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initCodingBookmarks();
      initInterviewBookmarks();
    });
  } else {
    initCodingBookmarks();
    initInterviewBookmarks();
  }
}
