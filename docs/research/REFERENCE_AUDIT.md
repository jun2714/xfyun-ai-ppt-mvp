# 007 reference implementation audit

## Fixed revisions

- Presenton: `1a1b7ae6134b31d7465d8f7fd065c1c9fa8eff97` (Apache-2.0)
- PPTAgent: `2419d30b134a71486523e95ded60b32489fd3c61` (MIT)

The repositories are stored outside this workspace under `C:\Users\mr_zh\Documents\jingzhe\ppt-references` and are not runtime dependencies.

## Adopted ideas

- Provider isolation for text and image models.
- Separately observable planning, generation, asset and export stages.
- Editable presentation state and targeted page operations.
- Two-stage narrative/design workflow.
- Quality evaluation split into Content, Design and Coherence.

## Explicitly rejected

- Template IDs, template selection and HTML/Tailwind template execution.
- Reference-slide selection as the production layout engine.
- Model-produced coordinates, HTML, CSS, SVG, OOXML or executable presentation code.
- Scenario, title, page role or example keywords mapped to layouts.

No source code has been copied from either repository.
