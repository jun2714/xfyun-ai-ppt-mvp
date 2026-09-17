// Merge server image results into the current editor state without restoring old
// text/notes/geometry or resurrecting a deleted slide. No full-deck replacement.
export type ImageReplacementResult = {
  slide_id: string; path: (string | number)[]; previous_url: string | null;
  previous_ui: Record<string, any>; url: string;
};

export function mergeRepairedImages<T>(local: T, remote: unknown, replacements: ImageReplacementResult[] = []): T {
  const result = structuredClone(local) as any;
  const source = remote as any;
  const ready = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && !/placeholder/i.test(value);
  for (const slide of result.slides || []) {
    const saved = (source?.slides || []).find((candidate: any) => candidate.id === slide.id);
    if (!saved) continue;
    for (const item of replacements.filter(item => item.slide_id === slide.id)) {
      const at = (value: any) => item.path.reduce((node, key) => node?.[key], value);
      const target = at(slide.content), from = at(saved.content);
      if (!target || !from || (target.image_url || target.__image_url__ || null) !== (item.previous_url || null)
        || (from.image_url || from.__image_url__) !== item.url || !ready(item.url)
        || (target.image_prompt || target.__image_prompt__) !== (from.image_prompt || from.__image_prompt__)) continue;
      const component = slide.ui?.components?.find((c: any) => c.id === item.path[0]);
      const images: any[] = [];
      const visit = (node: any) => {
        if (!node || typeof node !== 'object') return;
        if (node.type === 'image' && node.name === item.path.at(-1)) images.push(node);
        else Object.values(node).forEach(visit);
      };
      visit(component);
      if (images.length !== 1 || ['data', 'prompt', 'fit', 'crop_scale', 'focus_x', 'focus_y'].some(
        key => (images[0][key] ?? null) !== (item.previous_ui[key] ?? null))) continue;
      target['__image_url__' in target ? '__image_url__' : 'image_url'] = item.url;
      if (from.__image_replacement__) target.__image_replacement__ = structuredClone(from.__image_replacement__);
      Object.assign(images[0], { data: item.url, fit: 'contain', crop_scale: 1, focus_x: 50, focus_y: 50 });
    }
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
