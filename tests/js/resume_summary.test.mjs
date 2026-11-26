import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../../static/js/modules/resume_summary.js", import.meta.url), "utf8");
const { buildResumeSummaries, summaryWordCount } = await import(
  `data:text/javascript,${encodeURIComponent(source)}`
);

test("returns three distinct targeted summaries made from reviewed facts", (t) => {
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("Summary generation must stay in the browser");
  });
  const review = {
    skills: ["React", "Python", "SQL", "python"],
    education: [{ degree: "Bachelor of Computing" }],
    projects: [{ title: "Seedling Catalogue" }],
    target_company: "Example Systems",
    job_description: "Python and Rust developers with Kubernetes experience",
    email: "private@example.invalid",
    summary: "Invented award and 100% improvement",
  };

  const summaries = buildResumeSummaries(review, "Backend Engineer");

  assert.equal(new Set(summaries).size, 3);
  assert.match(summaries[0], /^Skills include Python/);
  for (const text of summaries) {
    assert.match(text, /Backend Engineer opportunities at Example Systems/);
    assert.match(text, /Seedling Catalogue/);
    assert.doesNotMatch(text, /Rust|Kubernetes|Invented award|100%|private/);
    assert.ok(summaryWordCount(text) <= 50);
  }
});

test("keeps all three variants within budget when skills and targets are long", () => {
  const longFact = Array.from({ length: 12 }, (_, index) => `fact${index}`).join(" ");
  const summaries = buildResumeSummaries({
    skills: [`${longFact}!`, longFact.replace("fact0", "skill0"), longFact.replace("fact0", "skill1")],
    target_company: longFact,
  }, longFact);

  assert.equal(summaries.length, 3);
  assert.ok(summaries.every((text) => summaryWordCount(text) <= 50));
  assert.equal(buildResumeSummaries({ skills: [longFact.repeat(4)] }).length, 0);
});

test("returns an empty result without reviewed facts and leaves a general target out", () => {
  assert.deepEqual(buildResumeSummaries({ target_company: "Example Company" }, "Engineer"), []);
  const summaries = buildResumeSummaries({ education: [{ institution: "Cedar College" }], target_company: "General" });
  assert.equal(new Set(summaries).size, 3);
  assert.ok(summaries.every((text) => text.includes("Cedar College") && !text.includes("General")));
});
