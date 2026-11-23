/**
 * Accessible Chart Palette & Pattern Configuration (static/js/modules/chart_palette.js)
 * ===================================================================================
 * Implements the color-blind-safe Okabe & Ito (2002) barrier-free palette and
 * accessible canvas pattern fills (stripes, cross-hatch, dots) for Chart.js.
 *
 * Provides non-color visual cues (distinct line styles, point markers, symbols, and
 * pattern fills) so that charts remain fully legible and distinguishable:
 * - under red-green color blindness (Protanopia, Deuteranopia)
 * - under blue-yellow color blindness (Tritanopia)
 * - when printed or viewed in grayscale / monochrome (Achromatopsia)
 *
 * Ref: Okabe, M. & Ito, K. (2002). "Color Universal Design (CUD):
 *      How to make figures and presentations that are friendly to colorblind people."
 */

export const OKABE_ITO = Object.freeze({
  black: "#000000",
  orange: "#E69F00",
  skyBlue: "#56B4E9",
  bluishGreen: "#009E73",
  yellow: "#F0E442",
  blue: "#0072B2",
  vermilion: "#D55E00",
  reddishPurple: "#CC79A7",
});

export const ACCESSIBLE_PALETTE = Object.freeze({
  // Semantic status roles
  success: OKABE_ITO.bluishGreen,    // #009E73 (Matched, Passed, Positive)
  danger: OKABE_ITO.vermilion,       // #D55E00 (Missing, Failed, Negative)
  warning: OKABE_ITO.orange,         // #E69F00 (Needs Improvement, Moderate, Caution)
  primary: OKABE_ITO.blue,           // #0072B2 (Core metric, ATS Score, Fit)
  info: OKABE_ITO.skyBlue,           // #56B4E9 (Secondary comparison, Reference)
  accent: OKABE_ITO.reddishPurple,   // #CC79A7 (Tertiary metric)
  highlight: OKABE_ITO.yellow,       // #F0E442 (Callout, High priority)
  neutral: OKABE_ITO.black,          // #000000 (Base neutral / text)
});

/**
 * Standard non-color line chart dataset configurations.
 * Each dataset couples an Okabe-Ito color with a unique point marker symbol and line dash style.
 */
export const LINE_DATASET_CONFIGS = Object.freeze([
  {
    borderColor: OKABE_ITO.blue,
    backgroundColor: "rgba(0, 114, 178, 0.12)",
    pointBackgroundColor: OKABE_ITO.blue,
    pointBorderColor: "#ffffff",
    borderDash: [],
    pointStyle: "circle",
    pointRadius: 6,
    pointHoverRadius: 8,
    markerSymbol: "●",
    labelPrefix: "●",
  },
  {
    borderColor: OKABE_ITO.bluishGreen,
    backgroundColor: "rgba(0, 158, 115, 0.12)",
    pointBackgroundColor: OKABE_ITO.bluishGreen,
    pointBorderColor: "#ffffff",
    borderDash: [6, 4],
    pointStyle: "rectRot",
    pointRadius: 6,
    pointHoverRadius: 8,
    markerSymbol: "◆",
    labelPrefix: "◆",
  },
  {
    borderColor: OKABE_ITO.vermilion,
    backgroundColor: "rgba(213, 94, 0, 0.10)",
    pointBackgroundColor: OKABE_ITO.vermilion,
    pointBorderColor: "#ffffff",
    borderDash: [3, 3],
    pointStyle: "triangle",
    pointRadius: 6,
    pointHoverRadius: 8,
    markerSymbol: "▲",
    labelPrefix: "▲",
  },
  {
    borderColor: OKABE_ITO.orange,
    backgroundColor: "rgba(230, 159, 0, 0.12)",
    pointBackgroundColor: OKABE_ITO.orange,
    pointBorderColor: "#ffffff",
    borderDash: [8, 4, 2, 4],
    pointStyle: "rect",
    pointRadius: 6,
    pointHoverRadius: 8,
    markerSymbol: "■",
    labelPrefix: "■",
  },
]);

/**
 * Creates an accessible CanvasPattern for use in bar, pie, and doughnut charts.
 * When colors are desaturated or printed in black & white, the tactile pattern remains
 * clearly distinguishable.
 *
 * @param {CanvasRenderingContext2D} ctx - Target 2D rendering context
 * @param {"diagonal-stripes" | "cross-hatch" | "dots" | "horizontal-stripes" | "solid"} patternType
 * @param {string} color - Primary stroke/fill color (e.g. hex or rgba)
 * @param {string} [bgColor="transparent"] - Background fill color
 * @param {number} [size=16] - Size of repeating pattern cell in pixels
 * @returns {CanvasPattern | string} Canvas pattern or fallback color
 */
export function createAccessiblePattern(ctx, patternType, color, bgColor = "transparent", size = 16) {
  if (typeof document === "undefined" || !ctx || typeof ctx.createPattern !== "function") {
    return color;
  }

  if (patternType === "solid") {
    return color;
  }

  const pCanvas = document.createElement("canvas");
  pCanvas.width = size;
  pCanvas.height = size;
  const pctx = pCanvas.getContext("2d");
  if (!pctx) return color;

  if (bgColor && bgColor !== "transparent") {
    pctx.fillStyle = bgColor;
    pctx.fillRect(0, 0, size, size);
  }

  pctx.strokeStyle = color;
  pctx.fillStyle = color;
  pctx.lineWidth = 2.5;
  pctx.lineCap = "round";

  if (patternType === "diagonal-stripes") {
    // 45-degree diagonal stripes
    pctx.beginPath();
    pctx.moveTo(0, size);
    pctx.lineTo(size, 0);
    pctx.moveTo(-size / 2, size / 2);
    pctx.lineTo(size / 2, -size / 2);
    pctx.moveTo(size / 2, size * 1.5);
    pctx.lineTo(size * 1.5, size / 2);
    pctx.stroke();
  } else if (patternType === "cross-hatch") {
    // Grid / cross-hatch pattern
    pctx.beginPath();
    // Horizontal
    pctx.moveTo(0, size / 2);
    pctx.lineTo(size, size / 2);
    // Vertical
    pctx.moveTo(size / 2, 0);
    pctx.lineTo(size / 2, size);
    pctx.stroke();
  } else if (patternType === "dots") {
    // Polka dots
    pctx.beginPath();
    pctx.arc(size / 2, size / 2, 3, 0, 2 * Math.PI);
    pctx.fill();
    pctx.beginPath();
    pctx.arc(0, 0, 2, 0, 2 * Math.PI);
    pctx.arc(size, 0, 2, 0, 2 * Math.PI);
    pctx.arc(0, size, 2, 0, 2 * Math.PI);
    pctx.arc(size, size, 2, 0, 2 * Math.PI);
    pctx.fill();
  } else if (patternType === "horizontal-stripes") {
    // Horizontal stripes
    pctx.beginPath();
    pctx.moveTo(0, size / 4);
    pctx.lineTo(size, size / 4);
    pctx.moveTo(0, (size * 3) / 4);
    pctx.lineTo(size, (size * 3) / 4);
    pctx.stroke();
  } else {
    return color;
  }

  const pattern = ctx.createPattern(pCanvas, "repeat");
  return pattern || color;
}

/**
 * Returns accessible colors and high-contrast text/grid scales based on the current active theme.
 */
export function getChartThemeTokens(isDark = false) {
  return {
    textColor: isDark ? "#f0f2f5" : "#1f1f1f",
    subtextColor: isDark ? "#c4c7c5" : "#444746",
    gridColor: isDark ? "rgba(255, 255, 255, 0.12)" : "rgba(0, 0, 0, 0.08)",
    surfaceBg: isDark ? "#1e2022" : "#ffffff",
    borderColor: isDark ? "#444746" : "#dadce0",
  };
}

// Expose globally for inline script compatibility across server-rendered templates
if (typeof window !== "undefined") {
  window.ChartPalette = {
    OKABE_ITO,
    ACCESSIBLE_PALETTE,
    LINE_DATASET_CONFIGS,
    createAccessiblePattern,
    getChartThemeTokens,
  };
}

export default {
  OKABE_ITO,
  ACCESSIBLE_PALETTE,
  LINE_DATASET_CONFIGS,
  createAccessiblePattern,
  getChartThemeTokens,
};
