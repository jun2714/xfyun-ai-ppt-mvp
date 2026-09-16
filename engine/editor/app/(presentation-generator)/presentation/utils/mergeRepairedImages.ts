// Merge server image results into the current editor state without restoring old
// text/notes/geometry or resurrecting a deleted slide. No full-deck replacement.
export function mergeRepairedImages<T>(local: T, remote: unknown): T {
  const result = structuredClone(local) as any;
  const source = remote as any;
  const ready = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && !/placeholder/i.test(value);
  for (const slide of result.slides || []) {
    const saved = (source?.slides || []).find((candidate: any) => candidate.id === slide.id);
    if (!saved) continue;
    const merge = (target: any, from: any, path: string[] = []) => {
      if (!target || !from || typeof target !== 'object' || typeof from !== 'object') return;
      const prompt = target.image_prompt || target.__image_prompt__;
      const previous = target.image_url || target.__image_url__;
      const url = from.image_url || from.__image_url__;
      if (prompt && prompt === (from.image_prompt || from.__image_prompt__) && !ready(previous) && ready(url)) {
        const component = slide.ui?.components?.find((c: any) => c.id === path[0]);
        const images: any[] = [];
        const visit = (value: any) => {
          if (!value || typeof value !== 'object') return;
          if (value.type === 'image' && value.name === path.at(-1)) images.push(value);
          else Object.values(value).forEach(visit);
        };
        visit(component);
        const replacement = images.find(image => ready(image.data))?.data || url;
        target['__image_url__' in target ? '__image_url__' : 'image_url'] = replacement;
        images.forEach(image => { image.data = replacement; });
      }
      for (const key of Object.keys(target)) {
        if (target[key] && typeof target[key] === 'object') merge(target[key], from[key], [...path, key]);
      }
    };
    merge(slide.content, saved.content);
  }
  return result as T;
}
