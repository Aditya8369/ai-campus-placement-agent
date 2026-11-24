/**
 * Chart Accessibility Module (static/js/modules/chart_accessibility.js)
 * =====================================================================
 * Provides accessible alternative data tables for major application charts (#task-accessible-chart-tables):
 * - Seamless keyboard-navigable toggle between visual Chart.js canvas and semantic HTML data table.
 * - Explicit labels, column/row scopes, units of measurement, and descriptive captions.
 * - Keyboard focus management and screen reader live region announcements.
 * - Clear identification and styling of charts with empty/missing data states.
 */

/**
 * Initializes accessible data table toggles and keyboard navigation for all charts.
 */
export function initChartAccessibility() {
  const toggleButtons = document.querySelectorAll(".chart-table-toggle-btn");

  toggleButtons.forEach((btn) => {
    // Prevent duplicate listeners
    if (btn._hasChartA11yListener) return;
    btn._hasChartA11yListener = true;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      toggleChartTableView(btn);
    });

    // Keyboard support: Enter and Spacebar are handled natively by <button>,
    // but ensure standard behavior and avoid scrolling on Space.
    btn.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        btn.click();
      }
    });
  });

  // Verify and ensure empty chart states are properly identified
  detectAndAnnounceEmptyCharts();

  // Initialize radar chart on batch_compare page if canvas is present
  initBatchCompareRadar();
}

/**
 * Toggles the view between Chart.js visual canvas and semantic HTML data table.
 * @param {HTMLButtonElement} btn
 */
export function toggleChartTableView(btn) {
  const chartWrapperId = btn.getAttribute("data-target-chart");
  const tableWrapperId = btn.getAttribute("data-target-table");

  if (!chartWrapperId || !tableWrapperId) return;

  const chartWrapper = document.getElementById(chartWrapperId);
  const tableWrapper = document.getElementById(tableWrapperId);

  if (!chartWrapper || !tableWrapper) return;

  const isShowingTable = !tableWrapper.classList.contains("d-none");
  const toggleTextEl = btn.querySelector(".toggle-text") || btn;

  if (isShowingTable) {
    // Switch to Chart View
    tableWrapper.classList.add("d-none");
    chartWrapper.classList.remove("d-none");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("title", "Switch to accessible data table view");
    btn.innerHTML = '<i class="fa-solid fa-table me-1"></i> <span class="toggle-text">View Data Table</span>';

    announceAriaLive("Switched to visual chart view.");
    btn.focus();
  } else {
    // Switch to Table View
    chartWrapper.classList.add("d-none");
    tableWrapper.classList.remove("d-none");
    btn.setAttribute("aria-expanded", "true");
    btn.setAttribute("title", "Switch to visual chart view");
    btn.innerHTML = '<i class="fa-solid fa-chart-line me-1"></i> <span class="toggle-text">View Chart</span>';

    announceAriaLive("Switched to data table view. Use table navigation keys to explore data points.");

    // Keyboard Focus: Move focus to the table wrapper region so screen reader / keyboard users
    // can immediately explore rows with Arrow keys.
    if (typeof tableWrapper.focus === "function") {
      tableWrapper.focus();
    }
  }
}

/**
 * Checks for chart containers with empty or zero datasets and ensures accessible announcements.
 */
export function detectAndAnnounceEmptyCharts() {
  const emptyStates = document.querySelectorAll(".chart-empty-state");
  emptyStates.forEach((el) => {
    if (!el.getAttribute("role")) {
      el.setAttribute("role", "status");
    }
    if (!el.getAttribute("aria-live")) {
      el.setAttribute("aria-live", "polite");
    }
  });
}

/**
 * Announces status changes to screen readers via an accessible live region.
 * @param {string} message
 */
function announceAriaLive(message) {
  if (typeof document === "undefined") return;

  let announcer = document.getElementById("chartA11yLiveAnnouncer");
  if (!announcer) {
    announcer = document.createElement("div");
    announcer.id = "chartA11yLiveAnnouncer";
    announcer.setAttribute("aria-live", "polite");
    announcer.setAttribute("aria-atomic", "true");
    announcer.className = "visually-hidden";
    document.body.appendChild(announcer);
  }
  announcer.textContent = message;
}

/**
 * Initializes the Multi-Company Radar Chart on batch_compare.html if present.
 */
function initBatchCompareRadar() {
  const canvas = document.getElementById("companyRadarCanvas");
  if (!canvas || !window.Chart) return;

  // Don't re-init if already initialized
  if (canvas._chartInstance) return;

  let radarData = null;
  const rawRadar = canvas.getAttribute("data-radar");
  if (rawRadar) {
    try {
      radarData = JSON.parse(rawRadar);
    } catch (e) {
      console.warn("Could not parse data-radar JSON:", e);
    }
  }

  if (radarData && Array.isArray(radarData.datasets) && radarData.datasets.length > 0) {
    const isDark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    const textColor = isDark ? "#c4c7c5" : "#444746";
    const gridColor = isDark ? "rgba(255, 255, 255, 0.12)" : "rgba(0, 0, 0, 0.08)";

    const ctx = canvas.getContext("2d");
    const chart = new window.Chart(ctx, {
      type: "radar",
      data: radarData,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            min: 0,
            max: 100,
            ticks: {
              stepSize: 20,
              color: textColor,
              backdropColor: "transparent",
              font: { size: 10 }
            },
            grid: { color: gridColor },
            pointLabels: {
              color: textColor,
              font: { size: 11, weight: "bold" }
            }
          }
        },
        plugins: {
          legend: {
            display: false // Using custom accessible toggle pills
          }
        }
      }
    });

    canvas._chartInstance = chart;

    // Connect custom company pills to dataset visibility
    const toggleBtns = document.querySelectorAll(".radar-toggle-btn");
    toggleBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-dataset-index"), 10);
        if (!isNaN(idx) && chart.data.datasets[idx]) {
          const isVisible = chart.isDatasetVisible(idx);
          chart.setDatasetVisibility(idx, !isVisible);
          chart.update();
          btn.classList.toggle("active", !isVisible);
          btn.classList.toggle("opacity-50", isVisible);
          btn.setAttribute("aria-pressed", isVisible ? "false" : "true");
        }
      });
    });
  }
}

// Auto-run on DOM ready
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChartAccessibility);
  } else {
    initChartAccessibility();
  }
}

// Expose on window for inline scripts and templates
if (typeof window !== "undefined") {
  window.initChartAccessibility = initChartAccessibility;
  window.toggleChartTableView = toggleChartTableView;
}
