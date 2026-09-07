// Inspect unresolved slots before filtering the URLs eligible for HTTP checks.
// Otherwise one successful image can hide a sibling left on placeholder.jpg.
export const collectUnresolvedImageSlots = (value, page, source, path = [], found = []) => {
  if (!value || typeof value !== "object") return found;
  const unresolved = (url) => typeof url !== "string" || !url.trim() || /placeholder/i.test(url);
  if (value.type === "image" && value.decorative !== true && value.is_icon !== true && unresolved(value.data)) {
    found.push({ page, source, path, url: value.data || null });
  }
  for (const [key, child] of Object.entries(value)) {
    if (["image_url", "__image_url__"].includes(key) && unresolved(child)) {
      found.push({ page, source, path: [...path, key], url: child || null });
    } else if (child && typeof child === "object") {
      collectUnresolvedImageSlots(child, page, source, [...path, key], found);
    }
  }
  return found;
};


const renderedText = (element) =>
  Array.isArray(element?.runs) ? element.runs.map((run) => run?.text || "").join("").trim() : "";

export const collectUnreadableAudienceText = (value, page, minimumSize = 18, found = []) => {
  if (!value || typeof value !== "object") return found;
  if (value.type === "text" && value.decorative !== true && renderedText(value)) {
    const sizes = [
      Number(value.font?.size),
      ...(value.runs || []).map((run) => Number(run?.font?.size)),
    ].filter((size) => Number.isFinite(size) && size > 0);
    const actualSize = sizes.length ? Math.min(...sizes) : 0;
    if (actualSize < minimumSize) {
      found.push({ page, name: value.name || null, text: renderedText(value), fontSize: actualSize });
    }
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") {
      collectUnreadableAudienceText(child, page, minimumSize, found);
    }
  }
  return found;
};

export const collectEmptyVisualCards = (value, page, found = []) => {
  if (!value || typeof value !== "object") return found;
  const children = Array.isArray(value.children) ? value.children : [];
  const directImages = children.filter((child) => child?.type === "image" && child.decorative !== true);
  const directTexts = children.filter((child) => child?.type === "text" && child.decorative !== true);
  if (directImages.length && directTexts.length && directTexts.every((child) => !renderedText(child))) {
    found.push({ page, name: value.name || null, imageCount: directImages.length, textCount: directTexts.length });
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") collectEmptyVisualCards(child, page, found);
  }
  return found;
};
