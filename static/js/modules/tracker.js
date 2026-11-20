/**
 * Job Tracker & Company Explorer Module (static/js/modules/tracker.js)
 * ==================================================================
 * Interactive company research cards, preparation checklists, and tracker links.
 */

import { escapeHtml } from "./utils.js";

export function initCompanyExplorer() {
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

        const escapeHtml = (str) => {
          if (!str) return "";
          return String(str).replace(/[&<>"']/g, (m) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;"
          })[m]);
        };

        const lastUpdated = d.last_updated_display || d.last_updated || "Date unconfirmed";
        const sourceName = d.source_name || "Campus Placement Archives";
        const sourceUrl = d.source_url;
        const isVerified = Boolean(d.is_verified || d.verification_status === "verified");
        const isOutdated = Boolean(d.is_outdated);

        // Verification Badge
        const verificationBadgeHtml = isVerified
          ? `<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="fa-solid fa-circle-check me-1"></i>Verified Hiring Guide</span>`
          : `<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle px-2 py-1"><i class="fa-solid fa-compass me-1"></i>General Preparation Guide</span>`;

        // Last Updated / Freshness Badge
        const freshnessBadgeHtml = isOutdated
          ? `<span class="badge bg-warning-subtle text-warning border border-warning-subtle px-2 py-1"><i class="fa-solid fa-clock-rotate-left me-1"></i>Last Updated: ${escapeHtml(lastUpdated)}</span>`
          : `<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-2 py-1"><i class="fa-solid fa-calendar-check me-1"></i>Last Updated: ${escapeHtml(lastUpdated)}</span>`;

        // Source Link with external security attributes
        const sourceLinkHtml = (sourceUrl && (sourceUrl.startsWith("http://") || sourceUrl.startsWith("https://")))
          ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-outline-primary rounded-pill px-3 py-1 text-decoration-none"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Official Source Link</a>`
          : `<span class="badge bg-light text-muted border py-1 px-2"><i class="fa-solid fa-link-slash me-1"></i>Source Link Unavailable</span>`;

        // Outdated Warning Banner
        const outdatedWarningHtml = isOutdated
          ? `<div class="alert alert-warning border-warning-subtle d-flex align-items-start gap-2 p-3 rounded-3 mb-3">
               <i class="fa-solid fa-triangle-exclamation text-warning fs-5 mt-1"></i>
               <div class="small">
                 <strong>Notice: Verification Recommended for Current Season</strong>
                 <p class="mb-0 text-muted">${escapeHtml(d.outdated_warning || "This company hiring guide was last updated over a year ago. Hiring rounds, patterns, and eligibility may differ for the current recruitment season. Please verify with the official career portal before applying.")}</p>
               </div>
             </div>`
          : "";

        // Source Information Strip
        const sourceStripHtml = `
          <div class="p-3 bg-light rounded-3 border mb-3">
            <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
              <div>
                <span class="small text-muted d-block text-uppercase fw-semibold" style="font-size: 0.72rem; letter-spacing: 0.5px;">Information Source</span>
                <span class="small fw-bold text-dark"><i class="fa-solid fa-building-columns text-primary me-1"></i>${escapeHtml(sourceName)}</span>
                ${d.verified_by ? `<span class="small text-muted d-block" style="font-size: 0.75rem;">Verified by: ${escapeHtml(d.verified_by)}</span>` : ""}
              </div>
              <div>
                ${sourceLinkHtml}
              </div>
            </div>
          </div>
        `;

        // Section 1: Verified Information
        const eligibilityHtml = d.eligibility
          ? `<div class="mb-3">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-user-graduate text-success me-2"></i>Eligibility Criteria:</h6>
               <p class="small text-secondary mb-0 bg-white p-2 rounded border border-light-subtle">${escapeHtml(d.eligibility)}</p>
             </div>`
          : `<div class="mb-3">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-user-graduate text-success me-2"></i>Eligibility Criteria:</h6>
               <p class="small text-muted fst-italic mb-0 bg-white p-2 rounded border border-light-subtle">Eligibility criteria not officially specified. Consult your college placement cell for current cutoffs.</p>
             </div>`;

        const hiringProcessHtml = `
          <div class="mb-3">
            <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-list-check text-success me-2"></i>Hiring Process:</h6>
            <p class="small text-secondary mb-0 bg-white p-2 rounded border border-light-subtle">${escapeHtml(d.hiring_process || "Hiring process stages currently undergoing season update.")}</p>
          </div>
        `;

        const technicalRoundsHtml = `
          <div class="mb-3">
            <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-laptop-code text-success me-2"></i>Technical Rounds:</h6>
            <p class="small text-secondary mb-0 bg-white p-2 rounded border border-light-subtle">${escapeHtml(d.technical_rounds || "Technical round details currently being updated.")}</p>
          </div>
        `;

        const hrRoundsHtml = d.hr_rounds
          ? `<div class="mb-3">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-handshake text-success me-2"></i>HR & Cultural Evaluation:</h6>
               <p class="small text-secondary mb-0 bg-white p-2 rounded border border-light-subtle">${escapeHtml(d.hr_rounds)}</p>
             </div>`
          : "";

        // Section 2: General Preparation Suggestions
        const frequentTopicsHtml = Array.isArray(d.frequent_topics) && d.frequent_topics.length
          ? `<div class="mb-3">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-tags text-info me-2"></i>Frequent Topics (Aggregated Student Experiences):</h6>
               <div class="d-flex flex-wrap gap-1">${d.frequent_topics.map(t => `<span class="badge bg-light text-dark border">${escapeHtml(t)}</span>`).join(" ")}</div>
             </div>`
          : "";

        const requiredSkillsHtml = Array.isArray(d.required_skills) && d.required_skills.length
          ? `<div class="mb-3">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-code text-info me-2"></i>Recommended Preparation Skills:</h6>
               <div class="d-flex flex-wrap gap-1">${d.required_skills.map(s => `<span class="badge bg-primary-subtle text-primary border border-primary-subtle">${escapeHtml(s)}</span>`).join(" ")}</div>
             </div>`
          : "";

        const prepTipsHtml = d.prep_tips
          ? `<div class="mb-2">
               <h6 class="fw-bold small text-dark mb-1"><i class="fa-solid fa-lightbulb text-warning me-2"></i>Preparation Tips & Strategies:</h6>
               <div class="alert alert-light border small text-dark mb-0">${escapeHtml(d.prep_tips)}</div>
             </div>`
          : "";

        modalBody.innerHTML = `
          <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
            <h4 class="fw-bold text-primary mb-0">${escapeHtml(data.company)}</h4>
            <div class="d-flex flex-wrap gap-1 align-items-center">
              ${verificationBadgeHtml}
              ${freshnessBadgeHtml}
            </div>
          </div>
          <p class="text-secondary small mb-3">${escapeHtml(d.overview || "")}</p>

          ${outdatedWarningHtml}
          ${sourceStripHtml}

          <!-- Verified Information Card -->
          <div class="card border border-success-subtle rounded-3 mb-3 bg-success-subtle bg-opacity-10 p-3">
            <div class="d-flex align-items-center gap-2 mb-2 pb-2 border-bottom border-success-subtle">
              <span class="badge bg-success text-white"><i class="fa-solid fa-shield-halved me-1"></i>Verified</span>
              <h6 class="fw-bold mb-0 text-success">Confirmed Hiring Criteria & Process</h6>
            </div>
            ${eligibilityHtml}
            ${hiringProcessHtml}
            ${technicalRoundsHtml}
            ${hrRoundsHtml}
          </div>

          <!-- General Preparation Suggestions Card -->
          <div class="card border border-info-subtle rounded-3 mb-2 bg-info-subtle bg-opacity-10 p-3">
            <div class="d-flex align-items-center gap-2 mb-1 pb-2 border-bottom border-info-subtle">
              <span class="badge bg-info text-white"><i class="fa-solid fa-lightbulb me-1"></i>Guidance</span>
              <h6 class="fw-bold mb-0 text-info">General Preparation Suggestions</h6>
            </div>
            <p class="small text-muted fst-italic mb-3" style="font-size: 0.78rem;">
              <i class="fa-solid fa-circle-info me-1"></i>Note: Preparation tips and frequent topics represent aggregated interview experiences and community-guided suggestions; company assessment patterns may evolve per recruitment cycle.
            </p>
            ${frequentTopicsHtml}
            ${requiredSkillsHtml}
            ${prepTipsHtml}
          </div>

          <!-- Download 1-Page Cheat Sheet Action Strip (#433) -->
          <div class="d-flex justify-content-between align-items-center p-3 bg-light rounded-3 border mt-3">
            <div>
              <span class="small fw-bold text-dark d-block"><i class="fa-solid fa-file-pdf text-success me-1"></i>Printable 1-Page Cheat Sheet</span>
              <span class="small text-muted" style="font-size: 0.75rem;">Company overview, interview rounds, frequent topics, and skill gaps formatted for revision on the go.</span>
            </div>
            <a href="/company/${encodeURIComponent(data.company)}/cheat-sheet" class="btn btn-sm btn-success rounded-pill px-3 py-1.5 text-decoration-none">
              <i class="fa-solid fa-download me-1"></i>Download Cheat Sheet
            </a>
          </div>
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


if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCompanyExplorer);
  } else {
    initCompanyExplorer();
  }
}
