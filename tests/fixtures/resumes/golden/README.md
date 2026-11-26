# Résumé extraction corpus

The corpus contains 12 fictional PDF and DOCX documents. It covers single
columns, two columns, tables, alternate headings, two pages, and image-only
uploads. The fixtures contain no real personal data.

Run the corpus with scores visible.

```sh
python -m pytest -q -s tests/test_resume_golden_corpus.py
```

Each text fixture scores one point per expected phrase found in its canonical
section and one per expected extracted skill. Case and whitespace are
normalized. Each file must retain at least 90% of the expected items. Image-only
files must receive the existing unreadable-image error with OCR disabled.
The suite uses the local upload extractor and requires no AI credentials.

To add a sample, write fictional facts in `generate.py`, choose a rendering
path that represents the layout, and run the generator from the repository root.

```sh
python tests/fixtures/resumes/golden/generate.py
```

Review the binary fixtures and `expected.json` together. Set expectations from
the facts you authored before running the parser.
