# SparkDeck 007

SparkDeck 007 is a template-free AI presentation architecture for editable kindergarten presentations.

## Pipeline

`Brief → Narrative Outline → Design Intent → Composition Candidates → Asset Plan → Scene Graph → Quality → Editor/PPTX`

The model produces narrative and communication intent. It never produces coordinates, CSS, HTML, SVG or PPTX code. Generic layout primitives generate and score multiple candidates; the selected composition is compiled into the Scene Graph before any image request is allowed.

## Packages

- `presentation-model`: versioned 007 schemas and invariants.
- `design-language`: design intent to readable deterministic tokens.
- `composition-engine`: Stack/Grid/Flow/Overlay/Anchor candidate generation and scoring.
- `scene-graph`: shared preview/edit/export model and revision commands.
- `quality-engine`: Content/Design/Coherence/Export checks and visual-review batching.
- `pptx-export`: Scene Graph to editable native PPTX objects.

Reference research is documented in `docs/research/REFERENCE_AUDIT.md`; reference repositories are not runtime dependencies and no template code is copied.

## Commands

```bash
pnpm dev
pnpm verify
```
