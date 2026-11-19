/**
 * CTC to In-Hand Salary & Offer Comparison Calculator (#428).
 * Provides client-side real-time calculation, input validation,
 * sample data loading, and side-by-side comparative rendering.
 */

(function () {
  "use strict";

  function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function formatINR(amount) {
    const val = Math.round(Number(amount) || 0);
    const isNegative = val < 0;
    const valStr = String(Math.abs(val));

    if (valStr.length <= 3) {
      return (isNegative ? "-₹" : "₹") + valStr;
    }
    const lastThree = valStr.substring(valStr.length - 3);
    let remaining = valStr.substring(0, valStr.length - 3);
    const groups = [];
    while (remaining.length > 2) {
      groups.unshift(remaining.substring(remaining.length - 2));
      remaining = remaining.substring(0, remaining.length - 2);
    }
    if (remaining.length > 0) {
      groups.unshift(remaining);
    }
    return (isNegative ? "-₹" : "₹") + groups.join(",") + "," + lastThree;
  }

  const defaultAssumptions = {
    standard_deduction: 75000,
    basic_pay_percentage_of_fixed: 50.0,
    employee_pf_rate: 12.0,
    professional_tax_annual: 2400,
    health_and_education_cess_rate: 4.0,
    tax_rebate_limit_87a: 700000,
    tax_slabs: [
      { from: 0, to: 300000, rate: 0.0 },
      { from: 300000, to: 700000, rate: 5.0 },
      { from: 700000, to: 1000000, rate: 10.0 },
      { from: 1000000, to: 1200000, rate: 15.0 },
      { from: 1200000, to: 1500000, rate: 20.0 },
      { from: 1500000, to: null, rate: 30.0 }
    ]
  };

  const assumptions = window.CALCULATOR_ASSUMPTIONS || defaultAssumptions;

  function calculateTax(taxableIncome) {
    if (taxableIncome <= 0) return { slabTax: 0, cess: 0, totalTax: 0 };
    const rebateLimit = Number(assumptions.tax_rebate_limit_87a || 700000);
    if (taxableIncome <= rebateLimit) {
      return { slabTax: 0, cess: 0, totalTax: 0, rebateApplied: true };
    }

    let slabTax = 0;
    const slabs = assumptions.tax_slabs || defaultAssumptions.tax_slabs;

    for (const slab of slabs) {
      const from = Number(slab.from || 0);
      const to = slab.to !== null && slab.to !== undefined ? Number(slab.to) : null;
      const rate = Number(slab.rate || 0);

      if (taxableIncome > from) {
        const taxableInSlab = to !== null ? Math.min(taxableIncome, to) - from : taxableIncome - from;
        if (taxableInSlab > 0 && rate > 0) {
          slabTax += taxableInSlab * (rate / 100);
        }
      }
    }

    const cessRate = Number(assumptions.health_and_education_cess_rate || 4.0);
    const cess = slabTax * (cessRate / 100);
    const totalTax = slabTax + cess;

    return {
      slabTax: Math.round(slabTax),
      cess: Math.round(cess),
      totalTax: Math.round(totalTax),
      rebateApplied: false
    };
  }

  function computeOfferData(idx, companyName, fixed, variable, joining, pf) {
    const basicPct = Number(assumptions.basic_pay_percentage_of_fixed || 50);
    const pfRate = Number(assumptions.employee_pf_rate || 12);
    const profTaxAnn = Number(assumptions.professional_tax_annual || 2400);
    const profTaxMo = Math.round(profTaxAnn / 12);
    const stdDed = Number(assumptions.standard_deduction || 75000);

    const basicAnn = Math.round(fixed * (basicPct / 100));
    const basicMo = Math.round(basicAnn / 12);
    const pfAnn = Math.round(basicAnn * (pfRate / 100));
    const pfMo = Math.round(pfAnn / 12);

    const taxableIncome = Math.max(0, Math.round(fixed - stdDed));
    const taxRes = calculateTax(taxableIncome);
    const taxAnn = taxRes.totalTax;
    const taxMo = Math.round(taxAnn / 12);

    const grossMo = Math.round(fixed / 12);
    const deductionsMo = pfMo + profTaxMo + taxMo;
    const inHandMo = Math.max(0, grossMo - deductionsMo);
    const inHandAnn = inHandMo * 12;

    const totalCTC = Math.round(fixed + variable + joining + pf);

    return {
      index: idx,
      companyName: companyName || `Offer ${idx}`,
      fixedPay: fixed,
      variablePay: variable,
      joiningBonus: joining,
      employerPf: pf,
      totalCTC: totalCTC,
      grossMonthly: grossMo,
      basicMonthly: basicMo,
      pfMonthly: pfMo,
      profTaxMonthly: profTaxMo,
      taxMonthly: taxMo,
      deductionsMonthly: deductionsMo,
      inHandMonthly: inHandMo,
      inHandAnnual: inHandAnn,
      taxableIncome: taxableIncome,
      taxAnnual: taxAnn
    };
  }

  function showError(msg) {
    const errBox = document.getElementById("calculatorErrorBox");
    const errMsg = document.getElementById("calculatorErrorMessage");
    if (errBox && errMsg) {
      errMsg.textContent = msg;
      errBox.classList.remove("d-none");
    }
  }

  function clearError() {
    const errBox = document.getElementById("calculatorErrorBox");
    if (errBox) {
      errBox.classList.add("d-none");
    }
  }

  function readOffersFromForm() {
    clearError();
    const offers = [];

    for (let idx = 1; idx <= 3; idx++) {
      const compEl = document.getElementById(`comp_${idx}`);
      const fixedEl = document.getElementById(`fixed_${idx}`);
      const varEl = document.getElementById(`variable_${idx}`);
      const joinEl = document.getElementById(`joining_${idx}`);
      const pfEl = document.getElementById(`pf_${idx}`);

      if (!fixedEl) continue;

      const compName = (compEl ? compEl.value : "").trim() || `Offer ${idx}`;
      const fixedRaw = (fixedEl.value || "").trim();
      const varRaw = (varEl ? varEl.value : "0").trim() || "0";
      const joinRaw = (joinEl ? joinEl.value : "0").trim() || "0";
      const pfRaw = (pfEl ? pfEl.value : "0").trim() || "0";

      // If all inputs for this offer are completely empty, skip it (unless Offer 1)
      if (!fixedRaw && (varRaw === "0" || !varRaw) && (joinRaw === "0" || !joinRaw) && (pfRaw === "0" || !pfRaw)) {
        continue;
      }

      const fixed = Number(fixedRaw);
      const variable = Number(varRaw);
      const joining = Number(joinRaw);
      const pf = Number(pfRaw);

      // Validate rejection of negative or invalid inputs
      if (isNaN(fixed) || isNaN(variable) || isNaN(joining) || isNaN(pf)) {
        showError(`Offer ${idx}: Please enter valid numeric values for all components.`);
        return null;
      }

      if (fixed < 0 || variable < 0 || joining < 0 || pf < 0) {
        showError(`Offer ${idx}: Salary components cannot be negative. Please enter non-negative amounts.`);
        return null;
      }

      if (fixed > 1000000000 || variable > 1000000000 || joining > 1000000000) {
        showError(`Offer ${idx}: Input exceeds maximum allowable limit of ₹100 Crore.`);
        return null;
      }

      if (fixed <= 0) {
        showError(`Offer ${idx}: Annual Fixed Pay must be greater than zero.`);
        return null;
      }

      offers.push(computeOfferData(idx, compName, fixed, variable, joining, pf));
    }

    if (offers.length === 0) {
      showError("Please enter Annual Fixed Pay for at least one offer.");
      return null;
    }

    return offers;
  }

  function renderComparisonResults(offers) {
    const resultsSection = document.getElementById("comparisonResultsSection");
    if (!resultsSection) return;

    if (!offers || offers.length === 0) {
      resultsSection.classList.add("d-none");
      return;
    }

    // Determine Highlights
    let highestInHand = offers[0];
    let highestGuaranteed = offers[0];
    let highestCTC = offers[0];

    for (const off of offers) {
      if (off.inHandMonthly > highestInHand.inHandMonthly) highestInHand = off;
      if (off.fixedPay > highestGuaranteed.fixedPay) highestGuaranteed = off;
      if (off.totalCTC > highestCTC.totalCTC) highestCTC = off;
    }

    // Update Highlights Banner
    const inHandCoEl = document.getElementById("highlightInHandCompany");
    const inHandAmtEl = document.getElementById("highlightInHandAmount");
    if (inHandCoEl && inHandAmtEl) {
      inHandCoEl.textContent = highestInHand.companyName;
      inHandAmtEl.textContent = formatINR(highestInHand.inHandMonthly);
    }

    const guarCoEl = document.getElementById("highlightGuaranteedCompany");
    const guarAmtEl = document.getElementById("highlightGuaranteedAmount");
    if (guarCoEl && guarAmtEl) {
      guarCoEl.textContent = highestGuaranteed.companyName;
      guarAmtEl.textContent = formatINR(highestGuaranteed.fixedPay);
    }

    // Badge count
    const badgeCont = document.getElementById("resultsCountBadgeContainer");
    if (badgeCont) {
      badgeCont.innerHTML = `<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-3 py-2 rounded-pill fw-semibold">
        <i class="fa-solid fa-list-check me-1"></i> Comparing ${offers.length} Offer${offers.length > 1 ? "s" : ""}
      </span>`;
    }

    // Render Comparative Cards
    const cardsRow = document.getElementById("comparisonCardsRow");
    if (cardsRow) {
      cardsRow.innerHTML = offers.map((off) => {
        const isHighestInHand = off.inHandMonthly === highestInHand.inHandMonthly;
        const isHighestGuar = off.fixedPay === highestGuaranteed.fixedPay;
        const isHighestCTC = off.totalCTC === highestCTC.totalCTC;

        const borderClass = isHighestInHand ? "border-success border-2 shadow-sm" : "border";

        return `
          <div class="col-lg-${12 / offers.length} col-md-6">
            <div class="card p-3 rounded-4 ${borderClass} bg-white h-100 d-flex flex-column justify-content-between">
              <div>
                <div class="d-flex justify-content-between align-items-start mb-2">
                  <h5 class="fw-bold text-dark mb-0">${escapeHtml(off.companyName)}</h5>
                  <span class="badge bg-light text-secondary border rounded-pill">Offer #${off.index}</span>
                </div>

                <!-- Badges -->
                <div class="d-flex flex-wrap gap-1 mb-3">
                  ${isHighestInHand ? '<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill small"><i class="fa-solid fa-trophy me-1"></i>Top In-Hand</span>' : ""}
                  ${isHighestGuar ? '<span class="badge bg-primary-subtle text-primary border border-primary-subtle rounded-pill small"><i class="fa-solid fa-shield-halved me-1"></i>Top Guaranteed</span>' : ""}
                  ${isHighestCTC ? '<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill small"><i class="fa-solid fa-star me-1"></i>Top CTC</span>' : ""}
                </div>

                <!-- Monthly In-Hand Highlight -->
                <div class="p-3 bg-light rounded-3 text-center mb-3">
                  <span class="small text-muted d-block mb-1">Estimated Monthly Take-Home</span>
                  <div class="fs-3 fw-bold text-success">${formatINR(off.inHandMonthly)}</div>
                  <span class="small text-muted">per month in bank account</span>
                </div>

                <!-- Core Details -->
                <ul class="list-group list-group-flush small mb-3">
                  <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent px-0 py-1">
                    <span class="text-secondary">Headline CTC:</span>
                    <strong class="text-dark">${formatINR(off.totalCTC)}</strong>
                  </li>
                  <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent px-0 py-1">
                    <span class="text-secondary">Guaranteed Fixed:</span>
                    <span class="text-dark fw-semibold">${formatINR(off.fixedPay)}</span>
                  </li>
                  <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent px-0 py-1">
                    <span class="text-secondary">Variable Pay:</span>
                    <span class="text-muted">${formatINR(off.variablePay)}</span>
                  </li>
                  <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent px-0 py-1">
                    <span class="text-secondary">Joining Bonus:</span>
                    <span class="text-muted">${formatINR(off.joiningBonus)}</span>
                  </li>
                  <li class="list-group-item d-flex justify-content-between align-items-center bg-transparent px-0 py-1">
                    <span class="text-secondary">Monthly Deductions:</span>
                    <span class="text-danger">-${formatINR(off.deductionsMonthly)}</span>
                  </li>
                </ul>
              </div>

              <div class="pt-2 border-top text-center text-muted small">
                Annual In-Hand: <strong class="text-dark">${formatINR(off.inHandAnnual)}</strong>
              </div>
            </div>
          </div>
        `;
      }).join("");
    }

    // Render Comparative Table
    const tableHeaders = ["th-offer-1", "th-offer-2", "th-offer-3"];
    tableHeaders.forEach((thClass, i) => {
      const th = document.querySelector(`.${thClass}`);
      if (th) {
        if (i < offers.length) {
          th.textContent = offers[i].companyName;
          th.classList.remove("d-none");
        } else {
          th.classList.add("d-none");
        }
      }
    });

    const rows = [
      { label: "Headline CTC (Annual)", getter: (o) => formatINR(o.totalCTC), bold: true },
      { label: "Annual Fixed Pay (Guaranteed)", getter: (o) => formatINR(o.fixedPay) },
      { label: "Annual Variable Pay (Performance)", getter: (o) => formatINR(o.variablePay) },
      { label: "One-Time Joining Bonus", getter: (o) => formatINR(o.joiningBonus) },
      { label: "Annual Employer PF Contribution", getter: (o) => formatINR(o.employerPf) },
      { label: "Monthly Gross Fixed Salary", getter: (o) => formatINR(o.grossMonthly) },
      { label: "Monthly Employee PF Deduction (12%)", getter: (o) => `-${formatINR(o.pfMonthly)}`, textClass: "text-danger" },
      { label: "Monthly Professional Tax", getter: (o) => `-${formatINR(o.profTaxMonthly)}`, textClass: "text-danger" },
      { label: "Monthly Income Tax (TDS New Regime)", getter: (o) => `-${formatINR(o.taxMonthly)}`, textClass: "text-danger" },
      { label: "Total Monthly Deductions", getter: (o) => `-${formatINR(o.deductionsMonthly)}`, textClass: "text-danger fw-semibold" },
      { label: "ESTIMATED MONTHLY IN-HAND", getter: (o) => formatINR(o.inHandMonthly), highlightRow: true },
      { label: "Estimated Annual In-Hand", getter: (o) => formatINR(o.inHandAnnual), bold: true }
    ];

    const tbody = document.getElementById("comparisonTableBody");
    if (tbody) {
      tbody.innerHTML = rows.map((r) => {
        const rowClass = r.highlightRow ? "table-success fw-bold fs-6" : (r.bold ? "fw-bold" : "");
        const cells = offers.map((off) => {
          const val = r.getter(off);
          const tdClass = r.textClass ? r.textClass : "";
          return `<td class="text-center ${tdClass}">${val}</td>`;
        }).join("");

        return `
          <tr class="${rowClass}">
            <td class="fw-semibold text-dark">${r.label}</td>
            ${cells}
          </tr>
        `;
      }).join("");
    }

    resultsSection.classList.remove("d-none");
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Load Sample Offers Handler
  function loadSampleOffers() {
    const samples = [
      { comp: "Tech Startup X", fixed: 1200000, variable: 300000, joining: 100000, pf: 72000 },
      { comp: "Enterprise Major Y", fixed: 1400000, variable: 100000, joining: 0, pf: 84000 },
      { comp: "Product Unicorn Z", fixed: 1000000, variable: 800000, joining: 200000, pf: 60000 }
    ];

    samples.forEach((s, idx) => {
      const i = idx + 1;
      const compEl = document.getElementById(`comp_${i}`);
      const fixedEl = document.getElementById(`fixed_${i}`);
      const varEl = document.getElementById(`variable_${i}`);
      const joinEl = document.getElementById(`joining_${i}`);
      const pfEl = document.getElementById(`pf_${i}`);

      if (compEl) compEl.value = s.comp;
      if (fixedEl) fixedEl.value = s.fixed;
      if (varEl) varEl.value = s.variable;
      if (joinEl) joinEl.value = s.joining;
      if (pfEl) pfEl.value = s.pf;
    });

    const calculated = readOffersFromForm();
    if (calculated) {
      renderComparisonResults(calculated);
    }
  }

  function resetOffers() {
    clearError();
    for (let i = 1; i <= 3; i++) {
      const compEl = document.getElementById(`comp_${i}`);
      const fixedEl = document.getElementById(`fixed_${i}`);
      const varEl = document.getElementById(`variable_${i}`);
      const joinEl = document.getElementById(`joining_${i}`);
      const pfEl = document.getElementById(`pf_${i}`);

      if (compEl) compEl.value = `Offer ${i}`;
      if (fixedEl) fixedEl.value = "";
      if (varEl) varEl.value = "0";
      if (joinEl) joinEl.value = "0";
      if (pfEl) pfEl.value = "0";
    }

    const resultsSection = document.getElementById("comparisonResultsSection");
    if (resultsSection) {
      resultsSection.classList.add("d-none");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const btnCalc = document.getElementById("btnCalculateOffers");
    if (btnCalc) {
      btnCalc.addEventListener("click", function () {
        const calculated = readOffersFromForm();
        if (calculated) {
          renderComparisonResults(calculated);
        }
      });
    }

    const btnSample = document.getElementById("btnLoadSampleOffers");
    if (btnSample) {
      btnSample.addEventListener("click", loadSampleOffers);
    }

    const btnReset = document.getElementById("btnResetOffers");
    if (btnReset) {
      btnReset.addEventListener("click", resetOffers);
    }

    // Auto-calculate on input enter key
    const form = document.getElementById("ctcCalculatorForm");
    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        const calculated = readOffersFromForm();
        if (calculated) {
          renderComparisonResults(calculated);
        }
      });
    }
  });
})();
