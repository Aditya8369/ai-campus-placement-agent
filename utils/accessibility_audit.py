import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag


NAMED_COLORS: Dict[str, str] = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "gray": "#808080",
    "grey": "#808080",
    "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3",
    "darkgray": "#a9a9a9",
    "darkgrey": "#a9a9a9",
    "navy": "#000080",
    "teal": "#008080",
    "orange": "#ffa500",
    "purple": "#800080",
}


@dataclass
class AccessibilityViolation:
    rule_id: str
    severity: str
    location: str
    message: str


def parse_color_to_rgb(raw_color: str) -> Optional[Tuple[int, int, int]]:
    """
    Converts CSS hex (#rgb, #rrggbb, #rrggbbaa), rgb()/rgba(), or named color
    into an (R, G, B) tuple (0-255). Returns None if unsupported or transparent.
    """
    if not raw_color:
        return None

    value = raw_color.strip().lower()
    if value in ("transparent", "inherit", "initial", "unset", "currentcolor"):
        return None

    if value in NAMED_COLORS:
        value = NAMED_COLORS[value]

    hex_match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})", value)
    if hex_match:
        hex_str = hex_match.group(1)
        if len(hex_str) in (3, 4):
            r = int(hex_str[0] * 2, 16)
            g = int(hex_str[1] * 2, 16)
            b = int(hex_str[2] * 2, 16)
            if len(hex_str) == 4 and int(hex_str[3] * 2, 16) == 0:
                return None
            return (r, g, b)
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        if len(hex_str) == 8 and int(hex_str[6:8], 16) == 0:
            return None
        return (r, g, b)

    rgb_match = re.fullmatch(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([0-9.]+))?\s*\)",
        value,
    )
    if rgb_match:
        r = min(255, int(rgb_match.group(1)))
        g = min(255, int(rgb_match.group(2)))
        b = min(255, int(rgb_match.group(3)))
        alpha = rgb_match.group(4)
        if alpha is not None and float(alpha) < 0.1:
            return None
        return (r, g, b)

    return None


def relative_luminance(rgb: Tuple[int, int, int]) -> float:
    """Computes WCAG 2.1 relative luminance for an sRGB color."""
    channels = []
    for channel in rgb:
        srgb = channel / 255.0
        if srgb <= 0.03928:
            channels.append(srgb / 12.92)
        else:
            channels.append(((srgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(fg: Tuple[int, int, int], bg: Tuple[int, int, int]) -> float:
    """Computes WCAG 2.1 contrast ratio between foreground and background RGB colors."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _extract_css_variables(css_text: str) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    for match in re.finditer(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;}{]+);", css_text):
        variables[match.group(1).strip()] = match.group(2).strip()
    return variables


def _resolve_css_var(value: str, variables: Dict[str, str], depth: int = 0) -> str:
    if depth > 5 or "var(" not in value:
        return value.strip()

    def replacer(match: re.Match) -> str:
        inner = match.group(1)
        parts = [p.strip() for p in inner.split(",", 1)]
        var_name = parts[0]
        fallback = parts[1] if len(parts) > 1 else ""
        resolved = variables.get(var_name, fallback)
        return _resolve_css_var(resolved, variables, depth + 1)

    return re.sub(r"var\(\s*([^)]+)\s*\)", replacer, value).strip()


def audit_css_contrast(css_text: str, min_ratio: float = 4.5) -> List[AccessibilityViolation]:
    """
    Audits CSS rule blocks that declare both `color` and `background` / `background-color`
    to ensure WCAG 2.1 AA normal-text contrast (>= 4.5:1) or large-text (>= 3.0:1).
    """
    violations: List[AccessibilityViolation] = []
    cleaned_css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    css_vars = _extract_css_variables(cleaned_css)

    for block_match in re.finditer(r"([^{}@]+)\{([^{}]+)\}", cleaned_css):
        selector = " ".join(block_match.group(1).strip().split())
        declarations = block_match.group(2)

        fg_raw: Optional[str] = None
        bg_raw: Optional[str] = None
        is_large_text = False

        for decl in declarations.split(";"):
            if ":" not in decl:
                continue
            prop, val = decl.split(":", 1)
            prop = prop.strip().lower()
            val = _resolve_css_var(val.strip(), css_vars)
            val = re.sub(r"\s*!important\s*$", "", val, flags=re.IGNORECASE).strip()

            if prop == "color":
                fg_raw = val
            elif prop in ("background-color", "background"):
                if "gradient(" not in val and "url(" not in val:
                    bg_raw = val
            elif prop == "font-size":
                px_match = re.search(r"(\d+(?:\.\d+)?)px", val)
                rem_match = re.search(r"(\d+(?:\.\d+)?)rem", val)
                if px_match and float(px_match.group(1)) >= 24.0:
                    is_large_text = True
                elif rem_match and float(rem_match.group(1)) >= 1.5:
                    is_large_text = True

        if fg_raw and bg_raw:
            fg_rgb = parse_color_to_rgb(fg_raw)
            bg_rgb = parse_color_to_rgb(bg_raw)
            if fg_rgb and bg_rgb:
                ratio = contrast_ratio(fg_rgb, bg_rgb)
                threshold = 3.0 if is_large_text else min_ratio
                if ratio < threshold:
                    violations.append(
                        AccessibilityViolation(
                            rule_id="color-contrast",
                            severity="serious",
                            location=f"CSS selector `{selector}`",
                            message=(
                                f"Insufficient color contrast {ratio:.2f}:1 "
                                f"(fg={fg_raw}, bg={bg_raw}; minimum required {threshold:.1f}:1)."
                            ),
                        )
                    )

    return violations


def _has_accessible_name(tag: Tag, soup: BeautifulSoup) -> bool:
    aria_label = (tag.get("aria-label") or "").strip()
    if aria_label:
        return True

    labelled_by = (tag.get("aria-labelledby") or "").strip()
    if labelled_by:
        for ref_id in labelled_by.split():
            ref_el = soup.find(id=ref_id)
            if ref_el and ref_el.get_text(strip=True):
                return True

    title = (tag.get("title") or "").strip()
    if title:
        return True

    visible_text = " ".join(tag.get_text(" ", strip=True).split())
    if visible_text:
        return True

    for img in tag.find_all("img"):
        if (img.get("alt") or "").strip():
            return True

    return False


def audit_html_accessibility(
    html_content: str,
    page_name: str = "page",
    check_inline_contrast: bool = True,
) -> List[AccessibilityViolation]:
    """
    Runs deterministic WCAG 2.1 accessibility checks on a rendered HTML document:
      1. Document language (`<html lang="...">`) and non-empty `<title>`
      2. Form controls (`input`, `select`, `textarea`) must have associated labels
      3. Valid heading hierarchy (must not skip levels e.g. h1 -> h3)
      4. Buttons and links must have discernible accessible names
      5. Images must declare `alt` attributes
      6. Inline style foreground/background contrast ratios (>= 4.5:1)
    """
    soup = BeautifulSoup(html_content, "html.parser")
    violations: List[AccessibilityViolation] = []

    # 1. Document metadata checks
    html_tag = soup.find("html")
    if html_tag is not None and not (html_tag.get("lang") or "").strip():
        violations.append(
            AccessibilityViolation(
                rule_id="html-has-lang",
                severity="serious",
                location=f"{page_name} <html>",
                message="Root <html> element is missing a non-empty `lang` attribute.",
            )
        )

    title_tag = soup.find("title")
    if title_tag is not None and not title_tag.get_text(strip=True):
        violations.append(
            AccessibilityViolation(
                rule_id="document-title",
                severity="serious",
                location=f"{page_name} <title>",
                message="Document <title> must not be empty.",
            )
        )

    # 2. Form control labels
    explicit_label_fors = {
        (lbl.get("for") or "").strip()
        for lbl in soup.find_all("label")
        if (lbl.get("for") or "").strip()
    }

    for control in soup.find_all(["input", "select", "textarea"]):
        ctrl_type = (control.get("type") or "").strip().lower()
        if control.name == "input" and ctrl_type in ("hidden", "submit", "reset", "button", "image"):
            if ctrl_type in ("submit", "reset", "button") and not (
                (control.get("value") or "").strip() or _has_accessible_name(control, soup)
            ):
                violations.append(
                    AccessibilityViolation(
                        rule_id="input-button-name",
                        severity="critical",
                        location=f"{page_name} <input type='{ctrl_type}'>",
                        message="Input button must have a non-empty value or accessible label.",
                    )
                )
            continue

        if control.has_attr("disabled") and control.get("aria-hidden") == "true":
            continue

        ctrl_id = (control.get("id") or "").strip()
        has_for_label = bool(ctrl_id and ctrl_id in explicit_label_fors)
        has_wrapping_label = control.find_parent("label") is not None
        has_aria = bool((control.get("aria-label") or "").strip())
        has_labelledby = False
        if control.get("aria-labelledby"):
            for ref_id in str(control.get("aria-labelledby")).split():
                ref_el = soup.find(id=ref_id)
                if ref_el and ref_el.get_text(strip=True):
                    has_labelledby = True

        if not (has_for_label or has_wrapping_label or has_aria or has_labelledby):
            ident = ctrl_id or control.get("name") or ctrl_type or control.name
            violations.append(
                AccessibilityViolation(
                    rule_id="label",
                    severity="critical",
                    location=f"{page_name} <{control.name} identifier='{ident}'>",
                    message=(
                        f"Form control `{ident}` lacks an associated <label for='...'>, "
                        "wrapping <label>, `aria-label`, or `aria-labelledby`."
                    ),
                )
            )

    # 3. Heading hierarchy (no skipped levels)
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    previous_level: Optional[int] = None
    for heading in headings:
        if heading.get("aria-hidden") == "true":
            continue
        level = int(heading.name[1])
        heading_text = " ".join(heading.get_text(" ", strip=True).split())[:60]
        if not heading_text:
            violations.append(
                AccessibilityViolation(
                    rule_id="empty-heading",
                    severity="moderate",
                    location=f"{page_name} <{heading.name}>",
                    message=f"Heading <{heading.name}> must not be empty.",
                )
            )
        if previous_level is not None and level > previous_level + 1:
            violations.append(
                AccessibilityViolation(
                    rule_id="heading-order",
                    severity="moderate",
                    location=f"{page_name} <{heading.name}> ('{heading_text}')",
                    message=(
                        f"Heading level skipped from <h{previous_level}> to <h{level}>. "
                        "Headings should increment by at most one level."
                    ),
                )
            )
        previous_level = level

    # 4. Button & interactive link accessible names
    for btn in soup.find_all("button"):
        if btn.get("aria-hidden") == "true":
            continue
        if not _has_accessible_name(btn, soup):
            btn_id = btn.get("id") or btn.get("class") or "unnamed-button"
            violations.append(
                AccessibilityViolation(
                    rule_id="button-name",
                    severity="critical",
                    location=f"{page_name} <button ({btn_id})>",
                    message=(
                        "Button has no discernible accessible name (missing text content, "
                        "`aria-label`, `aria-labelledby`, or `title`)."
                    ),
                )
            )

    for link in soup.find_all("a", href=True):
        if link.get("aria-hidden") == "true":
            continue
        if not _has_accessible_name(link, soup):
            href = link.get("href", "")
            violations.append(
                AccessibilityViolation(
                    rule_id="link-name",
                    severity="serious",
                    location=f"{page_name} <a href='{href}'>",
                    message="Anchor link has no discernible accessible text or `aria-label`.",
                )
            )

    # 5. Image alt attributes
    for img in soup.find_all("img"):
        if img.get("aria-hidden") == "true" or img.get("role") == "presentation":
            continue
        if not img.has_attr("alt"):
            src = img.get("src", "unknown")
            violations.append(
                AccessibilityViolation(
                    rule_id="image-alt",
                    severity="critical",
                    location=f"{page_name} <img src='{src}'>",
                    message="Image element is missing an `alt` attribute.",
                )
            )

    # 6. Inline style contrast checks
    if check_inline_contrast:
        for styled_el in soup.find_all(style=True):
            style_str = styled_el.get("style", "")
            inline_css = f"{styled_el.name} {{ {style_str} }}"
            for v in audit_css_contrast(inline_css):
                v.location = f"{page_name} <{styled_el.name} style='{style_str[:60]}'>"
                violations.append(v)

    return violations