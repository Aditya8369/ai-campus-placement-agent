/**
 * Frontend Bootstrap (static/js/script.js)
 * =========================================
 * Application bootstrap and backwards-compatibility module.
 * Modular feature code has been extracted to static/js/modules/:
 * - utils.js: CSRF helpers, escaping, toasts, clipboard helpers
 * - theme.js: Dark/light mode theme management
 * - common.js: Shared UI widgets (back-to-top, accessibility, session timeout, drawer)
 * - analysis.js: Resume upload, character counters, progress pipeline
 * - dashboard.js: Visualizations, skill gaps, roadmaps, walkthrough
 * - interview.js: Mock interview simulator, voice coach, timers, drafts
 * - bookmarks.js: Coding and interview question bookmarks
 * - tracker.js: Company explorer and checklists
 * - streaks.js: Preparation streaks and activity tracking
 * - auth.js: Password toggle and strength meter
 * - self_intro.js: Self-introduction pitch studio
 * - project_deep_dive.js: Architecture defense simulator
 * - cover_letter.js: Tailored cover letter studio
 */

import { getCsrfToken, escapeHtml, showToast, copyToClipboard } from "./modules/utils.js";
import { getPreferredTheme, setTheme, updateThemeIcon, initThemeToggle } from "./modules/theme.js";
import { initCommon, initBackToTop, initAccessibility, initRecentAnalysesDrawer, initSessionTimeout, clearAllInterviewDrafts, initInterviewDraftLogoutCleanup } from "./modules/common.js";
import { initFormUpload, initCharacterCounters, initCircularProgress } from "./modules/analysis.js";
import { initDashboard, initSkillGapFilter, initRoleSkillGapSelector, initRoadmapTracker, initRoadmapExport, initProgressTracker, initOutreachGenerator, initCopySuggestions, initRoleBasedPrep, initSkillsComparisonChart, initResumeKeywordHighlighter, initSectionFeedback, initUserWalkthrough } from "./modules/dashboard.js";
import { initMockInterview } from "./modules/interview.js";
import { initCodingBookmarks, initInterviewBookmarks } from "./modules/bookmarks.js";
import { initCompanyExplorer } from "./modules/tracker.js";
import { initStreakTracker } from "./modules/streaks.js";
import { initPasswordToggle, initPasswordStrengthIndicator } from "./modules/auth.js";
import { initSelfIntroductionStudio } from "./modules/self_intro.js";
import { initProjectDeepDive } from "./modules/project_deep_dive.js";
import { initTailoredCoverLetterStudio } from "./modules/cover_letter.js";

// Re-export for module consumers
export {
  getCsrfToken,
  escapeHtml,
  showToast,
  copyToClipboard,
  initThemeToggle,
  getPreferredTheme,
  setTheme,
  updateThemeIcon,
  initCommon,
  initBackToTop,
  initAccessibility,
  initRecentAnalysesDrawer,
  initSessionTimeout,
  clearAllInterviewDrafts,
  initInterviewDraftLogoutCleanup,
  initFormUpload,
  initCharacterCounters,
  initCircularProgress,
  initDashboard,
  initSkillGapFilter,
  initRoleSkillGapSelector,
  initRoadmapTracker,
  initRoadmapExport,
  initProgressTracker,
  initOutreachGenerator,
  initCopySuggestions,
  initRoleBasedPrep,
  initSkillsComparisonChart,
  initResumeKeywordHighlighter,
  initSectionFeedback,
  initUserWalkthrough,
  initMockInterview,
  initCodingBookmarks,
  initInterviewBookmarks,
  initCompanyExplorer,
  initStreakTracker,
  initPasswordToggle,
  initPasswordStrengthIndicator,
  initSelfIntroductionStudio,
  initProjectDeepDive,
  initTailoredCoverLetterStudio
};

// Expose public API on window for backwards compatibility with inline templates
if (typeof window !== "undefined") {
  window.getCsrfToken = getCsrfToken;
  window.escapeHtml = escapeHtml;
  window.showToast = showToast;
  window.copyToClipboard = copyToClipboard;
  window.clearAllInterviewDrafts = clearAllInterviewDrafts;
}

// Bootstrap on DOMContentLoaded
document.addEventListener("DOMContentLoaded", () => {
  initCommon();
  initFormUpload();
  initCircularProgress();
  initCharacterCounters();
  initMockInterview();
  initCompanyExplorer();
  initSkillGapFilter();
  initRoleSkillGapSelector();
  initRoadmapExport();
  initRoadmapTracker();
  initProgressTracker();
  if (typeof window.initCodingSandbox === "function") {
    window.initCodingSandbox();
  }
  initOutreachGenerator();
  initCopySuggestions();
  initRoleBasedPrep();
  initSkillsComparisonChart();
  initResumeKeywordHighlighter();
  initCodingBookmarks();
  initInterviewBookmarks();
  initStreakTracker();
  initSectionFeedback();
  initUserWalkthrough();
  initPasswordToggle();
  initPasswordStrengthIndicator();
  initSelfIntroductionStudio();
  initProjectDeepDive();
  initTailoredCoverLetterStudio();
});
