/**
 * Tailored Cover Letter Studio Module (static/js/modules/cover_letter.js)
 * =====================================================================
 * Generates and customizes grounded cover letters based on resume facts
 * and job descriptions, with tone toggles, live stats, copy, and downloads (#537).
 */

import { escapeHtml, showToast, getCsrfToken, countParas, countWords } from "./utils.js";

export function initTailoredCoverLetterStudio() {
  function countParas(text) {
    if (!text || !text.trim()) return 0;
    return text.trim().split(/\n\s*\n+/).filter(p => p.trim().length > 0).length;
  }

  function countWords(text) {
    if (!text || !text.trim()) return 0;
    return (text.trim().match(/\S+/g) || []).length;
  }

  // --- 1. Dashboard Studio Wiring (#pills-cover) ---
  const dashJdInput = document.getElementById("coverLetterJobDescInput");
  const dashCompanyInput = document.getElementById("coverLetterCompanyInput");
  const dashJdWarning = document.getElementById("coverLetterJdWarning");
  const dashFormalBtn = document.getElementById("coverLetterToneFormal");
  const dashFriendlyBtn = document.getElementById("coverLetterToneFriendly");
  const dashGenBtn = document.getElementById("btnGenerateTailoredLetter");
  const dashSpinner = document.getElementById("tailoredLetterSpinner");
  const dashIcon = document.getElementById("tailoredLetterIcon");
  const dashEditor = document.getElementById("coverLetterEditor");
  const dashParaCount = document.getElementById("coverLetterParaCount");
  const dashWordCount = document.getElementById("coverLetterWordCount");
  const dashCopyBtn = document.getElementById("btnCopyCoverLetter");
  const dashDocxBtn = document.getElementById("btnDownloadCoverDocx");
  const dashTxtBtn = document.getElementById("btnDownloadCoverTxt");

  let dashTone = "formal";

  if (dashFormalBtn && dashFriendlyBtn) {
    dashFormalBtn.addEventListener("click", () => {
      dashTone = "formal";
      dashFormalBtn.classList.add("btn-primary", "active");
      dashFormalBtn.classList.remove("btn-outline-secondary");
      dashFriendlyBtn.classList.add("btn-outline-secondary");
      dashFriendlyBtn.classList.remove("btn-primary", "active");
    });
    dashFriendlyBtn.addEventListener("click", () => {
      dashTone = "friendly";
      dashFriendlyBtn.classList.add("btn-primary", "active");
      dashFriendlyBtn.classList.remove("btn-outline-secondary");
      dashFormalBtn.classList.add("btn-outline-secondary");
      dashFormalBtn.classList.remove("btn-primary", "active");
    });
  }

  function updateDashStats() {
    if (!dashEditor) return;
    const txt = dashEditor.value || "";
    if (dashParaCount) dashParaCount.textContent = countParas(txt);
    if (dashWordCount) dashWordCount.textContent = countWords(txt);
  }

  if (dashEditor) {
    dashEditor.addEventListener("input", updateDashStats);
    updateDashStats();
  }

  if (dashGenBtn) {
    dashGenBtn.addEventListener("click", async () => {
      const jdText = dashJdInput ? dashJdInput.value.trim() : "";
      if (!jdText) {
        if (dashJdWarning) {
          dashJdWarning.classList.remove("d-none");
        }
        if (dashJdInput) dashJdInput.focus();
        return;
      }
      if (dashJdWarning) dashJdWarning.classList.add("d-none");

      const companyName = dashCompanyInput ? dashCompanyInput.value.trim() : "";
      const analysisId = dashGenBtn.getAttribute("data-analysis-id") || "";

      dashGenBtn.disabled = true;
      if (dashSpinner) dashSpinner.classList.remove("d-none");
      if (dashIcon) dashIcon.classList.add("d-none");

      try {
        const endpoint = analysisId
          ? `/api/analysis/${analysisId}/cover-letter`
          : "/api/cover-letter/generate";

        const payload = {
          job_description: jdText,
          company_name: companyName,
          tone: dashTone
        };

        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || "Failed to generate tailored cover letter");
        }

        if (dashEditor && data.cover_letter) {
          dashEditor.value = data.cover_letter;
          updateDashStats();
        }
      } catch (err) {
        console.error("Cover letter generation error:", err);
        if (dashJdWarning) {
          dashJdWarning.textContent = err.message || "An error occurred while generating cover letter.";
          dashJdWarning.classList.remove("d-none");
        }
      } finally {
        dashGenBtn.disabled = false;
        if (dashSpinner) dashSpinner.classList.add("d-none");
        if (dashIcon) dashIcon.classList.remove("d-none");
      }
    });
  }

  // Dashboard Copy button
  if (dashCopyBtn && dashEditor) {
    dashCopyBtn.addEventListener("click", async () => {
      const textToCopy = dashEditor.value;
      if (!textToCopy) return;
      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalHtml = dashCopyBtn.innerHTML;
        dashCopyBtn.innerHTML = '<i class="fa-solid fa-check text-success me-1"></i> Copied!';
        dashCopyBtn.classList.add("btn-success");
        dashCopyBtn.classList.remove("btn-outline-primary");
        setTimeout(() => {
          dashCopyBtn.innerHTML = originalHtml;
          dashCopyBtn.classList.remove("btn-success");
          dashCopyBtn.classList.add("btn-outline-primary");
        }, 2000);
      } catch (err) {
        console.error("Clipboard copy failed:", err);
      }
    });
  }

  // Common Download Function
  async function downloadCoverLetterFile(format, editorEl, companyEl) {
    if (!editorEl) return;
    const content = editorEl.value.trim();
    if (!content) return;
    const company = companyEl ? companyEl.value.trim() : "Company";

    try {
      const res = await fetch("/api/cover-letter/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: content,
          format: format,
          company_name: company
        })
      });

      if (!res.ok) throw new Error("Download request failed");

      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition");
      let filename = `Cover_Letter_${format.toLowerCase() === "txt" ? "Draft.txt" : "Draft.docx"}`;
      if (disposition && disposition.indexOf("filename=") !== -1) {
        const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
        if (matches != null && matches[1]) {
          filename = matches[1].replace(/['"]/g, "");
        }
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download failed:", err);
    }
  }

  if (dashDocxBtn && dashEditor) {
    dashDocxBtn.addEventListener("click", () => downloadCoverLetterFile("docx", dashEditor, dashCompanyInput));
  }
  if (dashTxtBtn && dashEditor) {
    dashTxtBtn.addEventListener("click", () => downloadCoverLetterFile("txt", dashEditor, dashCompanyInput));
  }

  // --- 2. Standalone Studio Wiring (/cover-letter) ---
  const saJdInput = document.getElementById("standaloneJdInput");
  const saResumeInput = document.getElementById("standaloneResumeInput");
  const saCompanyInput = document.getElementById("standaloneCompanyInput");
  const saJdWarning = document.getElementById("standaloneJdWarning");
  const saFormalBtn = document.getElementById("toneFormalBtn");
  const saFriendlyBtn = document.getElementById("toneFriendlyBtn");
  const saGenBtn = document.getElementById("btnStandaloneGenerate");
  const saRegenBtn = document.getElementById("btnStandaloneRegenerate");
  const saSpinner = document.getElementById("standaloneSpinner");
  const saIcon = document.getElementById("standaloneIcon");
  const saEditor = document.getElementById("standaloneLetterEditor");
  const saParaCount = document.getElementById("standaloneParaCount");
  const saWordCount = document.getElementById("standaloneWordCount");
  const saToneBadge = document.getElementById("standaloneToneBadge");
  const saCopyBtn = document.getElementById("btnStandaloneCopy");
  const saDocxBtn = document.getElementById("btnStandaloneDocx");
  const saTxtBtn = document.getElementById("btnStandaloneTxt");

  let saTone = "formal";

  function setSaTone(tone) {
    saTone = tone;
    if (saToneBadge) {
      saToneBadge.textContent = `Tone: ${tone.charAt(0).toUpperCase() + tone.slice(1)}`;
    }
    if (saFormalBtn && saFriendlyBtn) {
      if (tone === "formal") {
        saFormalBtn.classList.add("btn-primary", "active");
        saFormalBtn.classList.remove("btn-outline-secondary");
        saFriendlyBtn.classList.add("btn-outline-secondary");
        saFriendlyBtn.classList.remove("btn-primary", "active");
      } else {
        saFriendlyBtn.classList.add("btn-primary", "active");
        saFriendlyBtn.classList.remove("btn-outline-secondary");
        saFormalBtn.classList.add("btn-outline-secondary");
        saFormalBtn.classList.remove("btn-primary", "active");
      }
    }
  }

  if (saFormalBtn) saFormalBtn.addEventListener("click", () => setSaTone("formal"));
  if (saFriendlyBtn) saFriendlyBtn.addEventListener("click", () => setSaTone("friendly"));

  function updateSaStats() {
    if (!saEditor) return;
    const txt = saEditor.value || "";
    if (saParaCount) saParaCount.textContent = countParas(txt);
    if (saWordCount) saWordCount.textContent = countWords(txt);
  }

  if (saEditor) {
    saEditor.addEventListener("input", updateSaStats);
    updateSaStats();
  }

  async function generateStandaloneLetter() {
    const jdText = saJdInput ? saJdInput.value.trim() : "";
    if (!jdText) {
      if (saJdWarning) saJdWarning.classList.remove("d-none");
      if (saJdInput) saJdInput.focus();
      return;
    }
    if (saJdWarning) saJdWarning.classList.add("d-none");

    const resumeText = saResumeInput ? saResumeInput.value.trim() : "";
    const company = saCompanyInput ? saCompanyInput.value.trim() : "";
    const analysisId = saGenBtn ? saGenBtn.getAttribute("data-analysis-id") : "";

    if (saGenBtn) saGenBtn.disabled = true;
    if (saRegenBtn) saRegenBtn.disabled = true;
    if (saSpinner) saSpinner.classList.remove("d-none");
    if (saIcon) saIcon.classList.add("d-none");

    try {
      let endpoint = "/api/cover-letter/generate";
      let payload = {
        job_description: jdText,
        company_name: company,
        tone: saTone,
        resume_text: resumeText
      };

      if (analysisId) {
        endpoint = `/api/analysis/${analysisId}/cover-letter`;
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || "Failed to generate tailored cover letter");
      }

      if (saEditor && data.cover_letter) {
        saEditor.value = data.cover_letter;
        updateSaStats();
      }
    } catch (err) {
      console.error("Standalone cover letter generation error:", err);
      if (saJdWarning) {
        saJdWarning.innerHTML = `<i class="fa-solid fa-triangle-exclamation me-2"></i><strong>Error:</strong> ${err.message || 'Could not generate cover letter.'}`;
        saJdWarning.classList.remove("d-none");
      }
    } finally {
      if (saGenBtn) saGenBtn.disabled = false;
      if (saRegenBtn) saRegenBtn.disabled = false;
      if (saSpinner) saSpinner.classList.add("d-none");
      if (saIcon) saIcon.classList.remove("d-none");
    }
  }

  if (saGenBtn) saGenBtn.addEventListener("click", generateStandaloneLetter);
  if (saRegenBtn) saRegenBtn.addEventListener("click", generateStandaloneLetter);

  if (saCopyBtn && saEditor) {
    saCopyBtn.addEventListener("click", async () => {
      const textToCopy = saEditor.value;
      if (!textToCopy) return;
      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalHtml = saCopyBtn.innerHTML;
        saCopyBtn.innerHTML = '<i class="fa-solid fa-check text-success me-1"></i> Copied!';
        saCopyBtn.classList.add("btn-success");
        saCopyBtn.classList.remove("btn-outline-primary");
        setTimeout(() => {
          saCopyBtn.innerHTML = originalHtml;
          saCopyBtn.classList.remove("btn-success");
          saCopyBtn.classList.add("btn-outline-primary");
        }, 2000);
      } catch (err) {
        console.error("Clipboard copy failed:", err);
      }
    });
  }

  if (saDocxBtn && saEditor) {
    saDocxBtn.addEventListener("click", () => downloadCoverLetterFile("docx", saEditor, saCompanyInput));
  }
  if (saTxtBtn && saEditor) {
    saTxtBtn.addEventListener("click", () => downloadCoverLetterFile("txt", saEditor, saCompanyInput));
  }
}





if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTailoredCoverLetterStudio);
  } else {
    initTailoredCoverLetterStudio();
  }
}
