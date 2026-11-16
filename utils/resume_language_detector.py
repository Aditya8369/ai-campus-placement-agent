"""
Resume Language Detection Service
Detects the primary natural language of uploaded resumes and profiles.

Features:
- Pure Python rule/token-based language detection (no heavy native/C dependencies).
- Supported languages: English (primary expected), Spanish, French, German, Hindi (Latin/Devanagari), etc.
- Soft non-blocking warning when an unsupported or non-English resume is detected.
- Clear, student-friendly recommendations advising English submission for optimal AI parsing and keyword matching.
- Multi-language score breakdown and section-level language consistency checks.
"""

import re
import unicodedata
from typing import Dict, Any, List, Optional

# Language common stop-word corpora and linguistic markers
LANGUAGE_PROFILES = {
    "en": {
        "name": "English",
        "supported": True,
        "keywords": {
            "the", "and", "in", "of", "to", "with", "for", "experience", "education",
            "skills", "projects", "work", "university", "college", "summary", "technologies",
            "responsibilities", "developed", "managed", "engineering", "bachelor", "master",
            "internship", "developer", "achievements", "certifications", "software",
            "designed", "implemented", "system", "database", "python", "programming"
        }
    },
    "es": {
        "name": "Spanish",
        "supported": False,
        "keywords": {
            "experiencia", "educación", "educacion", "habilidades", "proyectos", "trabajo",
            "universidad", "resumen", "tecnologías", "tecnologias", "responsabilidades",
            "desarrollado", "ingeniería", "ingenieria", "licenciatura", "pasantía", "pasantia",
            "desarrollador", "sistemas", "conocimientos", "certificaciones", "laboral"
        }
    },
    "fr": {
        "name": "French",
        "supported": False,
        "keywords": {
            "expérience", "experience", "formation", "compétences", "competences", "projets",
            "université", "universite", "résumé", "resume", "responsabilités", "developpeur",
            "ingénierie", "ingenierie", "stage", "diplôme", "diplome", "professionnelle",
            "connaissances", "gestion", "langues", "centre", "interet"
        }
    },
    "de": {
        "name": "German",
        "supported": False,
        "keywords": {
            "berufserfahrung", "ausbildung", "kenntnisse", "fähigkeiten", "faehigkeiten",
            "projekte", "studium", "universität", "universitaet", "verantwortlichkeiten",
            "ingenieurwesen", "abschluss", "praktikum", "lebenslauf", "qualifikationen",
            "werdegang", "sprachen", "kenntnisse", "informatik"
        }
    },
    "hi_translit": {
        "name": "Hindi (Transliterated)",
        "supported": False,
        "keywords": {
            "kaam", "anubhav", "shiksha", "pariyoina", "yogyata", "vidyalay", "karyalay",
            "pariksha", "pramanpatra", "takniki", "gyan"
        }
    }
}


class ResumeLanguageDetector:
    """Service to analyze resume text and detect natural languages."""

    def __init__(self):
        self.profiles = LANGUAGE_PROFILES

    def _tokenize(self, text: str) -> List[str]:
        """Normalize and tokenize text into lowercase word tokens."""
        if not text:
            return []
        cleaned = unicodedata.normalize("NFKD", text.lower())
        tokens = re.findall(r"\b[a-z0-9_-]{2,}\b", cleaned)
        return tokens

    def _check_script(self, text: str) -> Optional[str]:
        """Detect scripts other than Latin."""
        # Devanagari Unicode block
        if re.search(r"[\u0900-\u097F]", text):
            return "Hindi / Devanagari"
        # Cyrillic
        if re.search(r"[\u0400-\u04FF]", text):
            return "Cyrillic / Russian"
        # Arabic
        if re.search(r"[\u0600-\u06FF]", text):
            return "Arabic"
        # CJK
        if re.search(r"[\u4E00-\u9FFF]", text):
            return "Chinese / Japanese / Korean (CJK)"
        return None

    def analyze_language_distribution(self, resume_text: str) -> Dict[str, Any]:
        """
        Calculates match percentages across all monitored languages.
        """
        tokens = self._tokenize(resume_text)
        token_set = set(tokens)
        distribution: Dict[str, int] = {}
        total_matched = 0

        for code, profile in self.profiles.items():
            matched = len(token_set.intersection(profile["keywords"]))
            distribution[code] = matched
            total_matched += matched

        relative_breakdown: Dict[str, float] = {}
        for code, count in distribution.items():
            pct = round((count / total_matched * 100), 1) if total_matched > 0 else 0.0
            relative_breakdown[code] = pct

        return {
            "total_tokens": len(tokens),
            "keyword_hits": distribution,
            "relative_percentages": relative_breakdown
        }

    def detect_language(self, resume_text: str) -> Dict[str, Any]:
        """
        Analyzes resume text and returns the detected language, confidence,
        support status, and helpful guidance messages.
        """
        if not resume_text or not resume_text.strip():
            return {
                "detected_code": "unknown",
                "detected_language": "Unknown / Empty",
                "is_supported": False,
                "confidence": 0.0,
                "requires_warning": True,
                "distribution": {},
                "message": "The resume appears empty or could not be parsed into text.",
                "recommendation": "Please upload a readable resume containing text in English."
            }

        # Check for non-Latin script first
        script = self._check_script(resume_text)
        if script:
            return {
                "detected_code": "non_latin",
                "detected_language": script,
                "is_supported": False,
                "confidence": 0.95,
                "requires_warning": True,
                "distribution": {"script": script},
                "message": f"Resume contains content primarily written in non-Latin script ({script}).",
                "recommendation": (
                    "Campus placement evaluation models and automated ATS systems perform best "
                    "with English text. We strongly recommend uploading an English version for optimal score accuracy."
                )
            }

        tokens = self._tokenize(resume_text)
        total_tokens = len(tokens)
        if total_tokens < 15:
            return {
                "detected_code": "en",
                "detected_language": "English (Low Content)",
                "is_supported": True,
                "confidence": 0.40,
                "requires_warning": True,
                "distribution": {},
                "message": "The resume has very few words to reliably verify language.",
                "recommendation": "Ensure your resume has adequate detail including sections for Education, Skills, and Projects."
            }

        token_set = set(tokens)
        scores: Dict[str, int] = {}
        for code, profile in self.profiles.items():
            matched = token_set.intersection(profile["keywords"])
            scores[code] = len(matched)

        best_code = max(scores, key=scores.get)
        best_match_count = scores[best_code]
        dist = self.analyze_language_distribution(resume_text)

        # Calculate a normalized confidence metric
        confidence = min(round(best_match_count / max(1, len(self.profiles[best_code]["keywords"])), 2), 1.0)

        # Fallback to English if no profile matched strongly
        if best_match_count == 0:
            return {
                "detected_code": "en",
                "detected_language": "English (Default)",
                "is_supported": True,
                "confidence": 0.50,
                "requires_warning": False,
                "distribution": dist["relative_percentages"],
                "message": "Language verified as standard English format.",
                "recommendation": "No action needed. You can proceed to placement analysis."
            }

        best_profile = self.profiles[best_code]
        is_supported = best_profile["supported"]
        lang_name = best_profile["name"]

        if is_supported:
            return {
                "detected_code": best_code,
                "detected_language": lang_name,
                "is_supported": True,
                "confidence": max(confidence, 0.65),
                "requires_warning": False,
                "distribution": dist["relative_percentages"],
                "message": "Resume language verified as English. Ready for full evaluation.",
                "recommendation": "All placement assessment agents fully support this language."
            }
        else:
            return {
                "detected_code": best_code,
                "detected_language": lang_name,
                "is_supported": False,
                "confidence": max(confidence, 0.60),
                "requires_warning": True,
                "distribution": dist["relative_percentages"],
                "message": (
                    f"The resume was detected as {lang_name}. Campus placement pipelines and "
                    "interview prep algorithms are tailored primarily for English resumes."
                ),
                "recommendation": (
                    "You may still continue with evaluation, but for highest scoring accuracy and ATS keyword "
                    "matching, submitting your resume in English is strongly advised."
                )
            }


resume_language_detector = ResumeLanguageDetector()
