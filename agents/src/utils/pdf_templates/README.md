# FINEX PDF templates

`eisvogel.latex` is the **unmodified Eisvogel 3.5.1 single-file release** from
[Wandmalfarbe/pandoc-latex-template](https://github.com/Wandmalfarbe/pandoc-latex-template/releases/tag/v3.5.1).
Upstream commit: `93cc5b8`. License: BSD-3-Clause, preserved in `LICENSE.eisvogel`.

Release archive: `Eisvogel-3.5.1.zip`.
SHA-256: `4d257eaeb16eb41c2acec8d5af45b1a4dbe8844e1bc7fb7e61637d7ca20eb699`.
Use the release artifact rather than the repository's multi-file source template.

`finex-warm.tex` contains the crayon notebook theme: warm paper, handwritten-style
headings, sketchy numbered labels, uneven pencil rules and small margin doodles.
Body text stays typeset for readability, with pastel yellow/mint table stripes.
Headings prefer KaiTi and Comic Sans MS; fallback fonts are FandolKai and TeX Gyre.
The larger cover text uses the rounded YouYuan face, falling back to FandolHei.

`report-layout.lua` formats the body AST before LaTeX output. It emphasizes common
financial terms and values with units, preserving existing emphasis, code, math
and link targets. Summary/risk blocks use breakable pastel panels, while fully
labeled lists in fundamentals, valuation and recommendations become two-column
tables. Unstructured lists retain their original form; no report facts are added.

`assets/finex-crayon-cover.png` is the full-page crayon illustration derived from
the user's reference: a blonde girl with a high bun, black bow, and a
charcoal-and-cream penguin jacket, waving from the lower right. It is a required,
repository-local runtime asset. The renderer passes its absolute path as an
Eisvogel template variable so a report
can live in any directory without losing its background. Text is typeset on top
of the image, rather than baked into the bitmap. See [the asset prompt](assets/PROMPTS.md).
Report generation itself does not invoke an image model.
Common rating stars and risk/check markers are rendered with vector/math symbols
so they do not disappear when a system font lacks emoji glyphs.

Document metadata and Chinese font selection live in `../pdf_styles.py`.
Rendering uses Pandoc 3 and XeLaTeX or Tectonic; see the project README for setup.
