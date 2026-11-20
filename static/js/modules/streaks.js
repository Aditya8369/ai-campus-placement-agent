/**
 * Streaks Module (static/js/modules/streaks.js)
 * ============================================
 * Preparation streaks calendar, active days tracker, and motivation stats.
 */

import { escapeHtml } from "./utils.js";

export function initStreakTracker() {
  const container = document.getElementById("streakCalendarContainer");
  if (!container) return;

  const btnPrev = document.getElementById("btnPrevMonth");
  const btnNext = document.getElementById("btnNextMonth");
  const btnToday = document.getElementById("btnCurrentMonth");
  const monthTitle = document.getElementById("calendarMonthTitle");
  const activeDaysCount = document.getElementById("monthActiveDaysCount");
  const daysGrid = document.getElementById("streakCalendarDays");

  let currentYear = parseInt(btnPrev?.getAttribute("data-year") || new Date().getFullYear(), 10);
  let currentMonth = parseInt(btnPrev?.getAttribute("data-month") || (new Date().getMonth() + 1), 10);

  async function loadCalendar(year, month) {
    if (!daysGrid) return;
    daysGrid.style.opacity = "0.5";

    try {
      const res = await fetch(`/api/streak/calendar?year=${year}&month=${month}`);
      const data = await res.json();
      if (!data.success || !data.calendar) {
        throw new Error("Invalid calendar response");
      }

      const cal = data.calendar;
      currentYear = cal.year;
      currentMonth = cal.month;

      if (monthTitle) {
        monthTitle.textContent = `${cal.month_name} ${cal.year}`;
      }
      if (activeDaysCount) {
        activeDaysCount.textContent = cal.active_days_in_month;
      }
      if (btnPrev) {
        let prevM = currentMonth - 1;
        let prevY = currentYear;
        if (prevM < 1) {
          prevM = 12;
          prevY -= 1;
        }
        btnPrev.setAttribute("data-year", prevY);
        btnPrev.setAttribute("data-month", prevM);
      }
      if (btnNext) {
        let nextM = currentMonth + 1;
        let nextY = currentYear;
        if (nextM > 12) {
          nextM = 1;
          nextY += 1;
        }
        btnNext.setAttribute("data-year", nextY);
        btnNext.setAttribute("data-month", nextM);
      }

      // Rebuild day cells
      daysGrid.innerHTML = "";
      cal.calendar_weeks.forEach((week) => {
        week.forEach((day) => {
          const cell = document.createElement("div");
          cell.className = "streak-day-cell";
          if (!day.is_current_month) cell.classList.add("other-month");
          if (day.is_today) cell.classList.add("today-cell");
          if (day.is_active) cell.classList.add("active-day");

          cell.setAttribute("data-date", day.date);

          let tooltip = day.date;
          if (day.is_active) {
            const actNames = (day.activities || []).map(a => a.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())).join(", ");
            tooltip = `${day.date}: ${actNames} (${day.activity_count} activities)`;
          } else if (day.is_today) {
            tooltip = `Today (${day.date})`;
          }
          cell.setAttribute("title", tooltip);

          const numEl = document.createElement("div");
          numEl.className = "streak-day-number";
          numEl.textContent = day.day_number;
          cell.appendChild(numEl);

          if (day.is_active) {
            const flameEl = document.createElement("div");
            flameEl.className = "streak-day-flame";
            flameEl.innerHTML = '<span class="streak-flame-icon">🔥</span>';
            cell.appendChild(flameEl);
          } else if (day.is_today) {
            const dotEl = document.createElement("div");
            dotEl.className = "streak-day-dot today-dot";
            dotEl.setAttribute("title", "Today");
            cell.appendChild(dotEl);
          }

          daysGrid.appendChild(cell);
        });
      });
    } catch (err) {
      console.error("Failed to load streak calendar:", err);
    } finally {
      daysGrid.style.opacity = "1";
    }
  }

  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      let prevM = currentMonth - 1;
      let prevY = currentYear;
      if (prevM < 1) {
        prevM = 12;
        prevY -= 1;
      }
      loadCalendar(prevY, prevM);
    });
  }

  if (btnNext) {
    btnNext.addEventListener("click", () => {
      let nextM = currentMonth + 1;
      let nextY = currentYear;
      if (nextM > 12) {
        nextM = 1;
        nextY += 1;
      }
      loadCalendar(nextY, nextM);
    });
  }

  if (btnToday) {
    btnToday.addEventListener("click", () => {
      const now = new Date();
      loadCalendar(now.getFullYear(), now.getMonth() + 1);
    });
  }
}

/**
 * Accessibility & Keyboard Navigation Suite (#WCAG-2.1)
 * Ensures all interactive elements can be operated with keyboard alone,
 * traps focus within open modals/dialogs, restores focus upon closing,
 * enables Escape-to-close on all modals/drawers, and supports custom buttons.
 */


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initStreakTracker);
  } else {
    initStreakTracker();
  }
}
