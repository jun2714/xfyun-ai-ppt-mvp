# Kindergarten classroom rework — first implementation

Status: candidate, not classroom-approved. Do not merge based on CI alone.

## Implemented

- Preserve screen title, points, child instruction and teacher interaction as
  separate roles through lesson-to-outline conversion.
- Optional `audience_text` binds one visual asset to an exact screen point.
  Reordered assets cannot move a rain image underneath a sunlight caption.
- `kindergarten-classroom` is a code-owned cream-paper template family with
  large scene/observation pages and two-to-four bound visual cards. Exact point
  counts produce no leftover card header bars. It is automatically selected for
  visual lessons; explicit template selections and disabled-image mode remain
  compatible with their existing route.
- Classroom fields are mapped deterministically. No second paid text call is
  needed to rewrite or redistribute reviewed copy. Layout choice is also local.
- The family uses 48px headings and 32px body copy. A field that cannot hold the
  reviewed text at the classroom floor is rejected before image generation.
- Edited Markdown is authoritative. Stale screen metadata is never restored;
  stale visual requirements are dropped for an edited scene rather than silently
  pairing changed copy with the old image meaning.
- Teacher notes and interaction instructions can be reviewed/edited separately
  in the outline UI and are retained only as speaker notes.
- Explicit answer leakage, missing question/game contracts and missing reveal
  pages cannot be hidden by downgrading the semantic type to `other`.
- Browser probe audits title/point placement and image-prompt bindings, enforces
  the new 32px floor, and attempts an individual screenshot of each editor slide.

## Verification boundaries

Unit tests check schemas, capacity, actual UI hydration, exact bindings under
asset reordering, edited copy, no second model call, routing and content errors.
Prompt binding checks do not verify that the generated image pixels obeyed the
prompt. Every remote sample still needs a visual review for subject accuracy,
legibility, correspondence, pedagogy and narrative continuity.

## Still required

- Review a real eight-page sample and fix observed issues before any quality claim.
- Establish a teacher-approved reference lesson and broaden to multiple domains.
- Real visual consistency using reusable character/reference assets; a shared
  style prompt alone does not guarantee identical characters.
- True click-to-reveal/drag interaction is not introduced here. Question and
  answer are separate slides, not a simulated interactive game.
- More specialised compositions (action demonstration, memory, classification).
- Authenticated outer-platform save/reopen/export acceptance.
