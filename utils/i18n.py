"""
Internationalization (i18n) and Multilingual Localization Engine (#214).
Provides localized message catalogs and translation resolution for AI Campus Placement Agent.
Supported languages: English (en), Hindi (hi), Telugu (te), Spanish (es).
"""

from typing import Dict, Any, Optional

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "hi", "te", "es"]

LOCALE_NAMES = {
    "en": "English",
    "hi": "हिन्दी (Hindi)",
    "te": "తెలుగు (Telugu)",
    "es": "Español (Spanish)"
}

TRANSLATION_CATALOG: Dict[str, Dict[str, str]] = {
    "en": {
        "app_title": "AI Campus Placement Agent",
        "tagline": "AI-Powered Campus Placement Preparation Suite",
        "nav_home": "Home",
        "nav_login": "Login",
        "nav_register": "Register",
        "nav_logout": "Logout",
        "nav_applications": "Applications",
        "nav_history": "History",
        "nav_my_reports": "My Reports",
        "nav_compare": "Compare Versions",
        "nav_internships": "Find Internships",
        "nav_coding": "Practice DSA",
        "nav_interviews": "Interview History",
        "nav_settings": "Notification Settings",
        "nav_delete_account": "Delete Account",
        "btn_start_analysis": "Start Comprehensive Placement Analysis",
        "btn_upload_resume": "Upload PDF / DOCX",
        "btn_paste_text": "Paste Text",
        "btn_clear_form": "Clear Form",
        "btn_download_pdf": "Download Official Report",
        "label_select_company": "Target Company",
        "label_job_description": "Job Description (Optional)",
        "label_role_title": "Target Role Title",
        "status_applied": "Applied",
        "status_interview": "Interview",
        "status_selected": "Selected",
        "status_rejected": "Rejected",
        "hero_heading": "Crack Your Dream Campus Placement with Multi-Agent AI",
        "hero_subheading": "Instant ATS compatibility audits, bespoke interview simulations, and tailored skills roadmaps for leading tech recruiters.",
        "footer_copyright": "© 2026 AI Campus Placement Agent. All rights reserved.",
        "hero_title": "Prepare Smart. Get Placed Faster.",
        "hero_subtitle": "An intelligent multi-agent placement mentor that analyzes your resume, checks job description matches, suggests projects to bridge skill gaps, generates study roadmaps, and conducts interactive mock interviews.",
        "hero_badge_ats": "ATS Score Analysis",
        "hero_badge_projects": "Skill Gap Projects",
        "hero_badge_interview": "Live AI Mock Interviews",
        "workspace_title": "Placement Analysis Workspace",
        "features_heading": "Powered by Specialized AI Agents",
        "feature_resume_title": "Resume Analysis Agent",
        "feature_resume_desc": "Analyzes resume formatting, projects, experiences, and calculates an ATS compatibility score with targeted improvements.",
        "feature_job_title": "Job Matching Agent",
        "feature_job_desc": "Compares your skills and projects with target role job descriptions, generating exact match percentages and priority adjustments.",
        "feature_skill_title": "Skill Gap Agent",
        "feature_skill_desc": "Checks for missing skills, rates importance/learning complexity, and recommends custom learning pathways and micro-projects.",
        "feature_roadmap_title": "Learning Roadmap Agent",
        "feature_roadmap_desc": "Compiles a personalized 6-week preparation curriculum with estimated learning times, coding challenges, and weekly checkpoints.",
        "feature_interview_title": "Mock Interview Agent",
        "feature_interview_desc": "Generates tailored interview questions and evaluates your answers in real time with scoring.",
        "empty_analyses": "No placement analyses found. Upload your resume to begin preparation.",
        "empty_jobs": "No job applications tracked yet. Add your first opportunity above.",
        "lang_switch_success": "Interface language updated successfully."
    },
    "hi": {
        "app_title": "एआई कैंपस प्लेसमेंट एजेंट",
        "tagline": "एआई-संचालित कैंपस प्लेसमेंट तैयारी मंच",
        "nav_home": "मुख्य पृष्ठ",
        "nav_login": "लॉग इन करें",
        "nav_register": "पंजीकरण करें",
        "nav_logout": "लॉग आउट",
        "nav_applications": "आवेदन",
        "nav_history": "इतिहास",
        "nav_my_reports": "मेरी रिपोर्ट्स",
        "nav_compare": "संस्करण तुलना",
        "nav_internships": "इंटर्नशिप खोजें",
        "nav_coding": "कोडिंग अभ्यास",
        "nav_interviews": "साक्षात्कार इतिहास",
        "nav_settings": "अधिसूचना सेटिंग्स",
        "nav_delete_account": "खाता हटाएं",
        "btn_start_analysis": "प्लेसमेंट विश्लेषण शुरू करें",
        "btn_upload_resume": "पीडीएफ / डॉक्स अपलोड करें",
        "btn_paste_text": "टेक्स्ट पेस्ट करें",
        "btn_clear_form": "फॉर्म रीसेट करें",
        "btn_download_pdf": "आधिकारिक रिपोर्ट डाउनलोड करें",
        "label_select_company": "लक्षित कंपनी",
        "label_job_description": "नौकरी विवरण (वैकल्पिक)",
        "label_role_title": "पद का शीर्षक",
        "status_applied": "आवेदन किया गया",
        "status_interview": "साक्षात्कार",
        "status_selected": "चयनित",
        "status_rejected": "अस्वीकृत",
        "hero_heading": "मल्टी-एजेंट एआई के साथ अपनी पसंदीदा नौकरी हासिल करें",
        "hero_subheading": "शीर्ष तकनीकी कंपनियों के लिए त्वरित एटीएस ऑडिट, साक्षात्कार अभ्यास और कौशल रोडमैप।",
        "footer_copyright": "© 2026 एआई कैंपस प्लेसमेंट एजेंट। सर्वाधिकार सुरक्षित।",
        "hero_title": "स्मार्ट तैयारी करें। जल्दी प्लेसमेंट पाएं।",
        "hero_subtitle": "एक बुद्धिमान मल्टी-एजेंट मेंटर जो आपके बायोडाटा का विश्लेषण करता है, नौकरी विवरण से मिलान करता है, और मॉक इंटरव्यू आयोजित करता है।",
        "hero_badge_ats": "एटीएस स्कोर विश्लेषण",
        "hero_badge_projects": "कौशल अंतर प्रोजेक्ट्स",
        "hero_badge_interview": "लाइव एआई मॉक इंटरव्यू",
        "workspace_title": "प्लेसमेंट विश्लेषण वर्कस्पेस",
        "features_heading": "विशेषज्ञ एआई एजेंटों द्वारा संचालित",
        "feature_resume_title": "रिज्यूमे विश्लेषण एजेंट",
        "feature_resume_desc": "बायोडाटा फॉर्मेटिंग, प्रोजेक्ट्स और अनुभवों का विश्लेषण करता है।",
        "feature_job_title": "जॉब मैचिंग एजेंट",
        "feature_job_desc": "लक्षित भूमिका के अनुसार आपके कौशल और प्रोजेक्ट्स की तुलना करता है।",
        "feature_skill_title": "स्किल गैप एजेंट",
        "feature_skill_desc": "लापता कौशलों की पहचान करता है और सुधार की योजना सुझाता है।",
        "feature_roadmap_title": "लर्निंग रोडमैप एजेंट",
        "feature_roadmap_desc": "6-सप्ताह का व्यक्तिगत तैयारी पाठ्यक्रम तैयार करता है।",
        "feature_interview_title": "मॉक इंटरव्यू एजेंट",
        "feature_interview_desc": "साक्षात्कार प्रश्न उत्पन्न करता है और वास्तविक समय में उत्तरों का मूल्यांकन करता है।",
        "empty_analyses": "कोई विश्लेषण नहीं मिला। तैयारी शुरू करने के लिए अपना बायोडाटा अपलोड करें।",
        "empty_jobs": "अभी तक कोई आवेदन ट्रैक नहीं किया गया है।",
        "lang_switch_success": "भाषा सफलतापूर्वक बदल दी गई है।"
    },
    "te": {
        "app_title": "ఏఐ క్యాంపస్ ప్లేస్‌మెంట్ ఏజెంట్",
        "tagline": "ఏఐ ఆధారిత క్యాంపస్ ప్లేస్‌మెంట్ ప్రిపరేషన్ సూట్",
        "nav_home": "హోమ్",
        "nav_login": "లాగిన్",
        "nav_register": "రిజిస్టర్",
        "nav_logout": "లాగౌట్",
        "nav_applications": "దరఖాస్తులు",
        "nav_history": "చరిత్ర",
        "nav_my_reports": "నా నివేదికలు",
        "nav_compare": "పోలిక వెర్షన్లు",
        "nav_internships": "ఇంటర్న్‌షిప్‌లను కనుగొనండి",
        "nav_coding": "కోడింగ్ ప్రాక్టీస్",
        "nav_interviews": "ఇంటర్వ్యూ చరిత్ర",
        "nav_settings": "నోటిఫికేషన్ సెట్టింగ్‌లు",
        "nav_delete_account": "ఖాతాను తొలగించండి",
        "btn_start_analysis": "సమగ్ర ప్లేస్‌మెంట్ విశ్లేషణను ప్రారంభించండి",
        "btn_upload_resume": "పిడిఎఫ్ / డాక్స్ అప్‌లోడ్ చేయండి",
        "btn_paste_text": "టెక్స్ట్ పేస్ట్ చేయండి",
        "btn_clear_form": "ఫారమ్ క్లియర్ చేయండి",
        "btn_download_pdf": "రిపోర్ట్ డౌన్‌లోడ్ చేసుకోండి",
        "label_select_company": "లక్ష్య సంస్థ",
        "label_job_description": "ఉద్యోగ వివరణ (ఐచ్ఛికం)",
        "label_role_title": "ఉద్యోగ పాత్ర శీర్షిక",
        "status_applied": "దరఖాస్తు చేయబడింది",
        "status_interview": "ఇంటర్వ్యూ",
        "status_selected": "ఎంపికయ్యారు",
        "status_rejected": "తిరస్కరించబడింది",
        "hero_heading": "మల్టీ-ఏజెంట్ ఏఐ తో మీ కలల ప్లేస్‌మెంట్‌ను సాధించండి",
        "hero_subheading": "ముఖ్యమైన సాంకేతిక కంపెనీల కోసం ఖచ్చితమైన ఏటీఎస్ స్కోరు, మాక్ ఇంటర్వ్యూలు మరియు రోడ్‌మ్యాప్‌లు.",
        "footer_copyright": "© 2026 ఏఐ క్యాంపస్ ప్లేస్‌మెంట్ ఏజెంట్. సర్వహక్కులు ప్రత్యేకించబడ్డాయి.",
        "empty_analyses": "విశ్లేషణలు కనుగొనబడలేదు. ప్రారంభించడానికి మీ రెజ్యూమ్‌ను అప్‌లోడ్ చేయండి.",
        "empty_jobs": "ఇంకా ఉద్యోగ దరఖాస్తులు ఏవీ ట్రాక్ చేయబడలేదు.",
        "lang_switch_success": "భాష విజయవంతంగా నవీకరించబడింది."
    },
    "es": {
        "app_title": "Agente de Colocación Campus IA",
        "tagline": "Preparación de Colocación Laboral con Inteligencia Artificial",
        "nav_home": "Inicio",
        "nav_login": "Iniciar Sesión",
        "nav_register": "Registrarse",
        "nav_logout": "Cerrar Sesión",
        "nav_applications": "Postulaciones",
        "nav_history": "Historial",
        "nav_my_reports": "Mis Informes",
        "nav_compare": "Comparar Versiones",
        "nav_internships": "Buscar Pasantías",
        "nav_coding": "Práctica de Código",
        "nav_interviews": "Historial de Entrevistas",
        "nav_settings": "Configuración de Notificaciones",
        "nav_delete_account": "Eliminar Cuenta",
        "btn_start_analysis": "Iniciar Análisis de Colocación",
        "btn_upload_resume": "Subir PDF / DOCX",
        "btn_paste_text": "Pegar Texto",
        "btn_clear_form": "Limpiar Formulario",
        "btn_download_pdf": "Descargar Informe Oficial",
        "label_select_company": "Empresa Objetivo",
        "label_job_description": "Descripción del Puesto (Opcional)",
        "label_role_title": "Puesto Objetivo",
        "status_applied": "Postulado",
        "status_interview": "Entrevista",
        "status_selected": "Seleccionado",
        "status_rejected": "Rechazado",
        "hero_heading": "Consigue el Empleo de tus Sueños con IA Multi-Agente",
        "hero_subheading": "Auditorías ATS en tiempo real, simulaciones de entrevistas dinámicas y mapas de aprendizaje personalizados.",
        "footer_copyright": "© 2026 Agente de Colocación Campus IA. Todos los derechos reservados.",
        "empty_analyses": "No se encontraron análisis. Sube tu currículum para comenzar.",
        "empty_jobs": "Aún no hay postulaciones registradas.",
        "lang_switch_success": "Idioma de interfaz actualizado exitosamente."
    }
}


def get_translation(key: str, locale: Optional[str] = None, default: Optional[str] = None) -> str:
    """
    Retrieves the translated text for a specified dictionary key and locale (#214).
    Falls back to English if key is missing in the chosen locale, and returns default if not in English.
    """
    norm_locale = (locale or DEFAULT_LOCALE).strip().lower()
    if norm_locale not in TRANSLATION_CATALOG:
        norm_locale = DEFAULT_LOCALE

    # Check target locale
    locale_dict = TRANSLATION_CATALOG.get(norm_locale, {})
    if key in locale_dict:
        return locale_dict[key]

    # Fallback to English
    fallback_dict = TRANSLATION_CATALOG.get(DEFAULT_LOCALE, {})
    if key in fallback_dict:
        return fallback_dict[key]

    return default if default is not None else key


def get_all_translations_for_locale(locale: Optional[str] = None) -> Dict[str, str]:
    """
    Returns the complete key-value catalog for client-side JavaScript or full-page templating.
    """
    norm_locale = (locale or DEFAULT_LOCALE).strip().lower()
    if norm_locale not in TRANSLATION_CATALOG:
        norm_locale = DEFAULT_LOCALE

    # Merge English fallback with target locale
    merged = dict(TRANSLATION_CATALOG[DEFAULT_LOCALE])
    merged.update(TRANSLATION_CATALOG.get(norm_locale, {}))
    return merged
