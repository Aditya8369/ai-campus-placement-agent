"""
Accessible Chart Palette & Simulation Utilities (utils/chart_palette.py)
========================================================================
Implements the Okabe & Ito (2002) barrier-free color palette, accessible line
dataset stylings with distinct non-color markers, and Color Vision Deficiency
(CVD) simulation algorithms (Protanopia, Deuteranopia, Tritanopia, Grayscale)
for verifying that data visualizations remain distinguishable across all forms
of color blindness and monochrome printing.

References:
- Okabe, M. & Ito, K. (2002). "Color Universal Design (CUD)"
- Vienot, F., Brettel, H., & Mollon, J. D. (1999). Digital video colourmaps for
  checking the legibility of displays by dichromats. Color Research & Application.
"""

from typing import Dict, List, Tuple, Any, Optional
import math


# ---------------------------------------------------------------------------
# Canonical Okabe-Ito (2002) 8-Color Accessible Palette
# ---------------------------------------------------------------------------
OKABE_ITO_HEX: Dict[str, str] = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermilion": "#D55E00",
    "reddish_purple": "#CC79A7",
}

OKABE_ITO_RGB: Dict[str, Tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "orange": (230, 159, 0),
    "sky_blue": (86, 180, 233),
    "bluish_green": (0, 158, 115),
    "yellow": (240, 228, 66),
    "blue": (0, 114, 178),
    "vermilion": (213, 94, 0),
    "reddish_purple": (204, 121, 167),
}

# Semantic mapping for charts, statuses, and dashboards
ACCESSIBLE_PALETTE: Dict[str, str] = {
    "success": OKABE_ITO_HEX["bluish_green"],   # #009E73 (Matched, Passed, High Fit)
    "danger": OKABE_ITO_HEX["vermilion"],       # #D55E00 (Missing, Failed, Blocker)
    "warning": OKABE_ITO_HEX["orange"],         # #E69F00 (In-Progress, Moderate, Caution)
    "primary": OKABE_ITO_HEX["blue"],           # #0072B2 (ATS Score, Primary Target)
    "info": OKABE_ITO_HEX["sky_blue"],          # #56B4E9 (Secondary Metric, Reference)
    "accent": OKABE_ITO_HEX["reddish_purple"],  # #CC79A7 (Tertiary Category)
    "highlight": OKABE_ITO_HEX["yellow"],       # #F0E442 (Attention, Best Offer)
    "neutral": OKABE_ITO_HEX["black"],          # #000000 (Base text, Axis lines)
}

# ---------------------------------------------------------------------------
# Accessible Company Brand Palettes for Radar Charts (batch_analyzer.py)
# ---------------------------------------------------------------------------
COMPANY_ACCESSIBLE_PALETTES: Dict[str, Dict[str, Any]] = {
    "google": {
        "border": OKABE_ITO_HEX["blue"],                 # #0072B2
        "background": "rgba(0, 114, 178, 0.20)",
        "badge": "primary",
        "point_style": "circle",
        "marker": "●",
    },
    "microsoft": {
        "border": OKABE_ITO_HEX["bluish_green"],         # #009E73
        "background": "rgba(0, 158, 115, 0.20)",
        "badge": "success",
        "point_style": "rectRot",
        "marker": "◆",
    },
    "amazon": {
        "border": OKABE_ITO_HEX["orange"],               # #E69F00
        "background": "rgba(230, 159, 0, 0.20)",
        "badge": "warning",
        "point_style": "triangle",
        "marker": "▲",
    },
    "tcs": {
        "border": OKABE_ITO_HEX["sky_blue"],             # #56B4E9
        "background": "rgba(86, 180, 233, 0.20)",
        "badge": "info",
        "point_style": "rect",
        "marker": "■",
    },
    "infosys": {
        "border": OKABE_ITO_HEX["reddish_purple"],       # #CC79A7
        "background": "rgba(204, 121, 167, 0.20)",
        "badge": "purple",
        "point_style": "crossRot",
        "marker": "✖",
    },
    "accenture": {
        "border": OKABE_ITO_HEX["vermilion"],            # #D55E00
        "background": "rgba(213, 94, 0, 0.20)",
        "badge": "danger",
        "point_style": "star",
        "marker": "★",
    },
    "capgemini": {
        "border": OKABE_ITO_HEX["black"],                # #000000
        "background": "rgba(0, 0, 0, 0.18)",
        "badge": "dark",
        "point_style": "cross",
        "marker": "✚",
    },
    "wipro": {
        "border": OKABE_ITO_HEX["yellow"],               # #F0E442
        "background": "rgba(240, 228, 66, 0.30)",
        "badge": "warning",
        "point_style": "circle",
        "marker": "○",
    },
    "default": {
        "border": OKABE_ITO_HEX["blue"],                 # #0072B2
        "background": "rgba(0, 114, 178, 0.20)",
        "badge": "primary",
        "point_style": "circle",
        "marker": "●",
    },
}

DEFAULT_ACCESSIBLE_STYLE: Dict[str, Any] = {
    "border": OKABE_ITO_HEX["blue"],
    "background": "rgba(0, 114, 178, 0.20)",
    "badge": "primary",
    "point_style": "circle",
    "marker": "●",
}


# ---------------------------------------------------------------------------
# Color Parsing & WCAG 2.1 Contrast Calculations
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Parses a hex color string (#RGB, #RRGGBB) to an (R, G, B) tuple."""
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex color format: {hex_str}")
    return (
        int(cleaned[0:2], 16),
        int(cleaned[2:4], 16),
        int(cleaned[4:6], 16),
    )


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """Converts an RGB tuple (0-255) to uppercase hex string."""
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def relative_luminance(rgb: Tuple[int, int, int]) -> float:
    """Calculates WCAG 2.1 relative luminance for an RGB tuple."""
    channels = []
    for c in rgb:
        v = c / 255.0
        channels.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
    """Calculates WCAG 2.1 contrast ratio between two colors (range 1.0 to 21.0)."""
    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Color Vision Deficiency (CVD) Simulation Algorithms
# ---------------------------------------------------------------------------

def simulate_cvd(rgb: Tuple[int, int, int], deficiency: str) -> Tuple[int, int, int]:
    """
    Simulates color appearance under Color Vision Deficiencies.
    Supported modes:
    - 'protanopia': Red-blindness (loss of L-cones)
    - 'deuteranopia': Green-blindness (loss of M-cones)
    - 'tritanopia': Blue-blindness (loss of S-cones)
    - 'grayscale' / 'achromatopsia': Monochromatic luminance perception
    """
    mode = deficiency.strip().lower()

    if mode in ("grayscale", "monochrome", "achromatopsia"):
        # WCAG standard sRGB luminance projection
        lum = relative_luminance(rgb)
        # Convert linear luminance back to sRGB display value
        if lum <= 0.0031308:
            srgb_val = lum * 12.92
        else:
            srgb_val = 1.055 * (lum ** (1.0 / 2.4)) - 0.055
        byte_val = max(0, min(255, round(srgb_val * 255.0)))
        return (byte_val, byte_val, byte_val)

    # Linearize sRGB
    r_lin = (rgb[0] / 255.0) / 12.92 if (rgb[0] / 255.0) <= 0.04045 else (((rgb[0] / 255.0) + 0.055) / 1.055) ** 2.4
    g_lin = (rgb[1] / 255.0) / 12.92 if (rgb[1] / 255.0) <= 0.04045 else (((rgb[1] / 255.0) + 0.055) / 1.055) ** 2.4
    b_lin = (rgb[2] / 255.0) / 12.92 if (rgb[2] / 255.0) <= 0.04045 else (((rgb[2] / 255.0) + 0.055) / 1.055) ** 2.4

    if mode == "protanopia":
        # Vienot et al. (1999) Protanopia projection matrix
        r_sim = 0.11238 * r_lin + 0.88762 * g_lin + 0.00000 * b_lin
        g_sim = 0.11238 * r_lin + 0.88762 * g_lin + 0.00000 * b_lin
        b_sim = 0.00401 * r_lin + -0.00401 * g_lin + 1.00000 * b_lin
    elif mode == "deuteranopia":
        # Vienot et al. (1999) Deuteranopia projection matrix
        r_sim = 0.29275 * r_lin + 0.70725 * g_lin + 0.00000 * b_lin
        g_sim = 0.29275 * r_lin + 0.70725 * g_lin + 0.00000 * b_lin
        b_sim = -0.02234 * r_lin + 0.02234 * g_lin + 1.00000 * b_lin
    elif mode == "tritanopia":
        # Brettel et al. Tritanopia projection matrix
        r_sim = 1.00000 * r_lin + 0.14464 * g_lin + -0.14464 * b_lin
        g_sim = 0.00000 * r_lin + 0.85925 * g_lin + 0.14075 * b_lin
        b_sim = 0.00000 * r_lin + 0.85925 * g_lin + 0.14075 * b_lin
    else:
        raise ValueError(f"Unknown CVD mode: {deficiency}")

    # Gamma correct back to sRGB
    def unlinearize(val: float) -> int:
        clamped = max(0.0, min(1.0, val))
        if clamped <= 0.0031308:
            srgb = clamped * 12.92
        else:
            srgb = 1.055 * (clamped ** (1.0 / 2.4)) - 0.055
        return max(0, min(255, round(srgb * 255.0)))

    return (unlinearize(r_sim), unlinearize(g_sim), unlinearize(b_sim))


def color_perceptual_distance(rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
    """
    Computes Euclidean distance in sRGB space as a baseline metric for distinguishability.
    Pairs with distance >= 40 are clearly visually differentiated.
    """
    dr = rgb1[0] - rgb2[0]
    dg = rgb1[1] - rgb2[1]
    db = rgb1[2] - rgb2[2]
    return math.sqrt(dr * dr + dg * dg + db * db)


def verify_pair_distinguishability(
    hex1: str,
    hex2: str,
    min_dist: float = 30.0,
    min_lum_delta: float = 0.03,
    has_pattern_cue: bool = False,
) -> Dict[str, Any]:
    """
    Verifies that two palette colors remain distinct across standard CVD types:
    Protanopia, Deuteranopia, Tritanopia, and Grayscale.
    When has_pattern_cue is True, non-color pattern fills (stripes, hatch, markers)
    guarantee differentiation in monochrome.
    """
    c1 = hex_to_rgb(hex1)
    c2 = hex_to_rgb(hex2)

    results = {}
    for mode in ("protanopia", "deuteranopia", "tritanopia", "grayscale"):
        sim1 = simulate_cvd(c1, mode)
        sim2 = simulate_cvd(c2, mode)
        dist = color_perceptual_distance(sim1, sim2)
        lum_diff = abs(relative_luminance(sim1) - relative_luminance(sim2))
        is_distinct = (dist >= min_dist or lum_diff >= min_lum_delta) or (
            mode == "grayscale" and has_pattern_cue
        )
        results[mode] = {
            "c1_sim": rgb_to_hex(sim1),
            "c2_sim": rgb_to_hex(sim2),
            "distance": round(dist, 2),
            "luminance_delta": round(lum_diff, 4),
            "distinct": is_distinct,
        }

    return results
