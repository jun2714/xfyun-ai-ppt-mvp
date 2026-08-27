import type { Presentation, PresentationOutline, TemplateItem } from "../../entities/types";

export const AUTO_TEMPLATE_ID = "general";

function searchableTextParts(
  presentation: Presentation,
  outline: PresentationOutline,
) {
  return {
    topic: [
      presentation.title ?? "",
      presentation.content ?? "",
    ]
      .join("\n")
      .toLocaleLowerCase(),
    outline: outline.slides
      .map((slide) => slide.content ?? "")
      .join("\n")
      .toLocaleLowerCase(),
  };
}

function routingScore(
  template: TemplateItem,
  text: { topic: string; outline: string },
) {
  const metadata = template.routing_metadata;
  if (
    template.is_default === false ||
    metadata?.auto_match !== true ||
    metadata.quality_status === "failed"
  ) {
    return null;
  }

  const terms = metadata.routing_terms ?? [];
  const isAdultTemplate = metadata.audiences?.includes("adult") === true;
  const score = terms.reduce((total, rawTerm) => {
    const term = rawTerm.trim().toLocaleLowerCase();
    if (!term) return total;
    return (
      total +
      (text.topic.includes(term) ? 4 : 0) +
      (isAdultTemplate && text.topic.includes(term) ? 4 : 0) +
      (text.outline.includes(term) ? 1 : 0)
    );
  }, 0);

  return {
    score,
    priority: metadata.auto_priority ?? Number.MAX_SAFE_INTEGER,
  };
}

/**
 * Resolve the public "general / 自动匹配" option to one of the existing
 * kindergarten-oriented bundled templates.
 *
 * Manual selections never pass through this function: callers should invoke it
 * only when the selected template is AUTO_TEMPLATE_ID. The result is
 * deterministic so the same reviewed outline does not unexpectedly change
 * visual families between retries.
 */
export function resolveAutoTemplateId(
  presentation: Presentation,
  outline: PresentationOutline,
  templates: TemplateItem[],
): string {
  const text = searchableTextParts(presentation, outline);
  const ranked = templates
    .map((template) => ({ template, routing: routingScore(template, text) }))
    .filter(
      (item): item is {
        template: TemplateItem;
        routing: { score: number; priority: number };
      } => item.routing !== null,
    )
    .filter((item) => item.routing.score > 0)
    .sort(
      (left, right) =>
        right.routing.score - left.routing.score ||
        left.routing.priority - right.routing.priority ||
        left.template.id.localeCompare(right.template.id),
    );

  if (ranked[0]) return ranked[0].template.id;

  const fallback = templates
    .filter(
      (template) =>
        template.is_default !== false &&
        template.routing_metadata?.auto_match === true &&
        template.routing_metadata?.fallback === true,
    )
    .sort(
      (left, right) =>
        (left.routing_metadata?.auto_priority ?? Number.MAX_SAFE_INTEGER) -
          (right.routing_metadata?.auto_priority ?? Number.MAX_SAFE_INTEGER) ||
        left.id.localeCompare(right.id),
    )[0];

  // Preserve compatibility while older deployments are waiting for their
  // bundled template metadata to be re-imported on API restart.
  return fallback?.id ?? AUTO_TEMPLATE_ID;
}
