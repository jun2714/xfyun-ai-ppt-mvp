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
