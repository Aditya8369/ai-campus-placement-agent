"""
Tests for Accessible Chart Palette & Pattern Cues (tests/test_chart_palette.py)
=============================================================================
Validates:
1. Okabe-Ito (2002) barrier-free palette definitions and semantic mappings.
2. Color Vision Deficiency (CVD) simulations (Protanopia, Deuteranopia,
   Tritanopia, Grayscale) proving that categories remain distinct without color.
3. WCAG 2.1 AA contrast compliance for chart labels and text against light/dark themes.
4. Enforcement of non-color visual cues (distinct line styles, point markers,
   pattern fills, and status icons).
5. Template and frontend module integration across all chart-enabled pages.
"""

import pytest
import re
from pathlib import Path

from utils.chart_palette import (
    OKABE_ITO_HEX,
    OKABE_ITO_RGB,
    ACCESSIBLE_PALETTE,
    COMPANY_ACCESSIBLE_PALETTES,
    hex_to_rgb,
    rgb_to_hex,
    relative_luminance,
    contrast_ratio,
    simulate_cvd,
    color_perceptual_distance,
    verify_pair_distinguishability,
)
from utils.batch_analyzer import _get_company_style, COMPANY_PALETTES


class TestOkabeItoPalette:
    """Verifies that the shared configuration adheres to the Okabe-Ito specification."""

    def test_canonical_eight_colors_present(self):
        expected_keys = {
            "black", "orange", "sky_blue", "bluish_green",
            "yellow", "blue", "vermilion", "reddish_purple"
        }
        assert set(OKABE_ITO_HEX.keys()) == expected_keys
        assert set(OKABE_ITO_RGB.keys()) == expected_keys

    def test_exact_hex_codes(self):
        assert OKABE_ITO_HEX["black"].upper() == "#000000"
        assert OKABE_ITO_HEX["orange"].upper() == "#E69F00"
        assert OKABE_ITO_HEX["sky_blue"].upper() == "#56B4E9"
        assert OKABE_ITO_HEX["bluish_green"].upper() == "#009E73"
        assert OKABE_ITO_HEX["yellow"].upper() == "#F0E442"
        assert OKABE_ITO_HEX["blue"].upper() == "#0072B2"
        assert OKABE_ITO_HEX["vermilion"].upper() == "#D55E00"
        assert OKABE_ITO_HEX["reddish_purple"].upper() == "#CC79A7"

    def test_hex_rgb_conversions(self):
        for name, hex_val in OKABE_ITO_HEX.items():
            rgb = hex_to_rgb(hex_val)
            assert rgb == OKABE_ITO_RGB[name]
            assert rgb_to_hex(rgb).upper() == hex_val.upper()

    def test_semantic_status_mappings(self):
        # Matched/Success MUST be Bluish Green (#009E73), not red/green confusion green (#34A853)
        assert ACCESSIBLE_PALETTE["success"] == OKABE_ITO_HEX["bluish_green"]
        # Missing/Failure MUST be Vermilion (#D55E00), not generic red (#EA4335)
        assert ACCESSIBLE_PALETTE["danger"] == OKABE_ITO_HEX["vermilion"]
        # In-progress/Warning MUST be Orange (#E69F00)
        assert ACCESSIBLE_PALETTE["warning"] == OKABE_ITO_HEX["orange"]
        # Primary/ATS score MUST be Blue (#0072B2)
        assert ACCESSIBLE_PALETTE["primary"] == OKABE_ITO_HEX["blue"]


class TestColorVisionDeficiencySimulation:
    """
    Simulates color blindness and grayscale conversion to guarantee that
    visual indicators remain distinguishable without normal trichromatic vision.
    """

    @pytest.mark.parametrize("mode", ["protanopia", "deuteranopia", "tritanopia", "grayscale"])
    def test_matched_vs_missing_is_distinguishable(self, mode):
        """
        Crucial requirement: Red-green color blindness cannot tell standard red vs green apart.
        Verifies Okabe-Ito Bluish Green (#009E73) vs Vermilion (#D55E00) remain distinct.
        """
        success_rgb = hex_to_rgb(ACCESSIBLE_PALETTE["success"])
        danger_rgb = hex_to_rgb(ACCESSIBLE_PALETTE["danger"])

        sim_success = simulate_cvd(success_rgb, mode)
        sim_danger = simulate_cvd(danger_rgb, mode)

        # Perceptual color distance or luminance difference
        dist = color_perceptual_distance(sim_success, sim_danger)
        lum_diff = abs(relative_luminance(sim_success) - relative_luminance(sim_danger))

        # Under protanopia and deuteranopia, bluish-green and vermilion maintain a perceptible delta (>= 30)
        # In grayscale, luminance delta is >= 0.03, augmented by distinct non-color pattern fills
        assert dist >= 30.0 or lum_diff >= 0.03, (
            f"Insufficient separation under {mode}: distance={dist:.1f}, lum_delta={lum_diff:.3f}"
        )

    @pytest.mark.parametrize("mode", ["protanopia", "deuteranopia", "tritanopia", "grayscale"])
    def test_three_trend_series_remain_distinguishable(self, mode):
        """
        Verifies the 3 line-chart series:
        - Series 0: ATS Score (Blue #0072B2)
        - Series 1: Job Match (Bluish Green #009E73)
        - Series 2: Skill Gaps (Vermilion #D55E00)
        """
        c_ats = hex_to_rgb(OKABE_ITO_HEX["blue"])
        c_match = hex_to_rgb(OKABE_ITO_HEX["bluish_green"])
        c_gaps = hex_to_rgb(OKABE_ITO_HEX["vermilion"])

        sim_ats = simulate_cvd(c_ats, mode)
        sim_match = simulate_cvd(c_match, mode)
        sim_gaps = simulate_cvd(c_gaps, mode)

        # Check pairwise distances
        d_ats_match = color_perceptual_distance(sim_ats, sim_match)
        d_ats_gaps = color_perceptual_distance(sim_ats, sim_gaps)
        d_match_gaps = color_perceptual_distance(sim_match, sim_gaps)

        assert (d_ats_match >= 20.0 or abs(relative_luminance(sim_ats) - relative_luminance(sim_match)) >= 0.03)
        assert (d_ats_gaps >= 20.0 or abs(relative_luminance(sim_ats) - relative_luminance(sim_gaps)) >= 0.03)
        assert (d_match_gaps >= 20.0 or abs(relative_luminance(sim_match) - relative_luminance(sim_gaps)) >= 0.03)

    def test_verify_pair_distinguishability_helper(self):
        report = verify_pair_distinguishability(
            OKABE_ITO_HEX["bluish_green"],
            OKABE_ITO_HEX["vermilion"]
        )
        assert report["protanopia"]["distinct"] is True
        assert report["deuteranopia"]["distinct"] is True
        assert report["tritanopia"]["distinct"] is True
        assert report["grayscale"]["distinct"] is True


class TestContrastCompliance:
    """Verifies WCAG 2.1 AA text contrast compliance for chart labels."""

    def test_light_mode_labels_meet_wcag_aa(self):
        light_bg = (255, 255, 255)
        text_color = hex_to_rgb("#1F1F1F")
        ratio = contrast_ratio(text_color, light_bg)
        assert ratio >= 4.5, f"Contrast {ratio:.2f}:1 fails WCAG AA (>= 4.5:1 required)"

    def test_dark_mode_labels_meet_wcag_aa(self):
        dark_bg = hex_to_rgb("#1E2022")
        dark_text = hex_to_rgb("#F0F2F5")
        ratio = contrast_ratio(dark_text, dark_bg)
        assert ratio >= 4.5, f"Contrast {ratio:.2f}:1 fails WCAG AA (>= 4.5:1 required)"

    def test_vermilion_axis_ticks_meet_contrast(self):
        # Y1 right axis ticks in Vermilion (#D55E00) on white
        light_bg = (255, 255, 255)
        vermilion = hex_to_rgb(OKABE_ITO_HEX["vermilion"])
        ratio = contrast_ratio(vermilion, light_bg)
        # WCAG 2.1 AA allows 3.0:1 for large text/graphical UI components
        assert ratio >= 3.0, f"Contrast {ratio:.2f}:1 fails graphical component threshold (>= 3.0:1)"


class TestCompanyAccessiblePalettes:
    """Validates the radar chart company palettes in batch_analyzer.py."""

    def test_all_companies_have_non_color_markers(self):
        for company_name, style in COMPANY_ACCESSIBLE_PALETTES.items():
            assert "point_style" in style, f"Missing point_style for {company_name}"
            assert "marker" in style, f"Missing marker symbol for {company_name}"
            assert style["point_style"] in [
                "circle", "rectRot", "triangle", "rect", "crossRot", "star", "cross"
            ]

    def test_default_style_fallback(self):
        unknown_style = _get_company_style("nonexistent_firm_xyz")
        assert unknown_style["border"] == OKABE_ITO_HEX["blue"]
        assert unknown_style["point_style"] == "circle"
        assert unknown_style["marker"] == "●"


class TestStaticFilesAndTemplates:
    """Verifies that templates and scripts contain the accessible palette and non-color cues."""

    def test_js_chart_palette_module_exists(self):
        js_file = Path("static/js/modules/chart_palette.js")
        assert js_file.exists(), "static/js/modules/chart_palette.js must exist"
        content = js_file.read_text(encoding="utf-8")
        assert "OKABE_ITO" in content
        assert "createAccessiblePattern" in content
        assert "LINE_DATASET_CONFIGS" in content
        assert "window.ChartPalette" in content

    def test_dashboard_skills_chart_uses_patterns_and_icons(self):
        template = Path("templates/dashboard.html").read_text(encoding="utf-8")
        # Striped progress bar for non-color pattern
        assert "progress-bar-striped" in template
        # Check and cross icons in legend
        assert "fa-circle-check" in template
        assert "fa-circle-xmark" in template
        # Okabe-Ito colors in style
        assert "#009E73" in template
        assert "#D55E00" in template

    def test_dashboard_js_uses_okabe_ito_and_markers(self):
        js_mod = Path("static/js/modules/dashboard.js").read_text(encoding="utf-8")
        assert "chart_palette.js" in js_mod
        assert "OKABE_ITO.blue" in js_mod
        assert "OKABE_ITO.bluishGreen" in js_mod
        assert "OKABE_ITO.vermilion" in js_mod
        assert 'pointStyle: "rectRot"' in js_mod
        assert 'pointStyle: "triangle"' in js_mod

    def test_admin_ai_metrics_uses_patterns_and_symbols(self):
        template = Path("templates/admin_ai_metrics.html").read_text(encoding="utf-8")
        assert "chart_palette.js" in template
        assert "createAccessiblePattern" in template
        assert "✔ Successful Calls" in template
        assert "✖ Failed Calls" in template
        assert "● Average Latency" in template
        assert "◆ p95 Latency" in template

    def test_batch_compare_uses_accessible_radar_and_markers(self):
        template = Path("templates/batch_compare.html").read_text(encoding="utf-8")
        assert "companyRadarCanvas" in template
        assert "c.style.marker" in template
        assert "chart_palette.js" in template

    def test_compare_previous_uses_okabe_ito_blue_and_marker(self):
        template = Path("templates/compare_previous.html").read_text(encoding="utf-8")
        assert "#0072B2" in template
        assert "● ATS Score" in template

    def test_interview_history_uses_diamond_marker_and_blue(self):
        template = Path("templates/interview_history.html").read_text(encoding="utf-8")
        assert "#0072B2" in template
        assert "rectRot" in template
        assert "◆ Interview Score" in template

    def test_aptitude_palette_never_relies_on_color_alone(self):
        template = Path("templates/aptitude.html").read_text(encoding="utf-8")
        # Answered legend must include icon
        assert '<i class="fa-solid fa-check"' in template
