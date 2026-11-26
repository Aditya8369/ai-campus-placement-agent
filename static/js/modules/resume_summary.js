const MAX_WORDS = 50;

export function summaryWordCount(text) {
  return text.trim().split(/\s+/u).filter(Boolean).length;
}

function factText(value) {
  if (typeof value !== "string") return "";
  const text = value.replace(/\s+/gu, " ").trim().replace(/[.!?]+$/u, "");
  return text.length <= 120 && summaryWordCount(text) <= 12 ? text : "";
}

function terms(value) {
  return value.toLowerCase().match(/[\p{L}\p{N}+#]+/gu) ?? [];
}

export function buildResumeSummaries(review, targetRole = "") {
  const role = factText(targetRole);
  const company = factText(review.target_company);
  const targetCompany = company.toLowerCase() === "general" ? "" : company;
  const targetTerms = new Set(terms([role, targetCompany, review.job_description].join(" ")));
  const rank = (value) => terms(value).filter((word) => targetTerms.has(word)).length;
  const byRelevance = (a, b) => rank(b) - rank(a);

  const skills = [];
  const seenSkills = new Set();
  for (const value of review.skills ?? []) {
    const skill = factText(value);
    const key = skill.toLowerCase();
    if (!skill || seenSkills.has(key)) continue;
    seenSkills.add(key);
    skills.push(skill);
  }
  skills.sort(byRelevance);

  const project = (review.projects ?? [])
    .map(({ title }) => factText(title))
    .filter(Boolean)
    .sort(byRelevance)[0];
  const education = (review.education ?? [])
    .map(({ degree, field_of_study, institution }) =>
      [degree, field_of_study, institution].map(factText).find(Boolean),
    )
    .filter(Boolean)
    .sort(byRelevance)[0];

  if (!skills.length && !project && !education) return [];

  const target = role
    ? `Seeking ${role} opportunities${targetCompany ? ` at ${targetCompany}` : ""}.`
    : targetCompany ? `Seeking opportunities at ${targetCompany}.` : "";
  const targetWords = summaryWordCount(target);
  function skillSentence(prefix, count) {
    const selected = skills.slice(0, count);
    while (selected.length) {
      const sentence = `${prefix} ${selected.join(", ")}.`;
      if (summaryWordCount(sentence) + targetWords <= MAX_WORDS) return sentence;
      selected.pop();
    }
    return "";
  }

  const options = [
    [
      skillSentence("Skills include", 3),
      project && `Projects include ${project}.`,
      education && `Education includes ${education}.`,
    ],
    [
      project && `Project work includes ${project}.`,
      skillSentence("Technical skills include", 2),
      education && `Academic background includes ${education}.`,
    ],
    [
      education && `My education includes ${education}.`,
      skillSentence("My skills include", 1),
      project && `My projects include ${project}.`,
    ],
  ];

  return options.map((sentences) => {
    const included = [];
    let words = targetWords;
    for (const sentence of sentences.filter(Boolean)) {
      const length = summaryWordCount(sentence);
      if (words + length > MAX_WORDS) continue;
      included.push(sentence);
      words += length;
    }
    if (target && included.length) included.push(target);
    return included.join(" ");
  }).filter(Boolean);
}
