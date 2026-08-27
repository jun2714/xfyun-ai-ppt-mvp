export type SlideOutline = { content: string };

export type PresentationOutline = { slides: SlideOutline[] };

export type EngineSlide = {
  id: string;
  presentation: string;
  index: number;
  content: Record<string, unknown>;
  ui: Record<string, unknown>;
};

export type Presentation = {
  id: string;
  title: string | null;
  content: string;
  n_slides: number;
  language: string;
  created_at: string;
  updated_at: string;
  slides: EngineSlide[];
};

export type TemplateItem = {
  id: string;
  name: string;
  description?: string | null;
  layout_count: number;
  thumbnail?: string | null;
  routing_metadata?: {
    audiences?: string[];
    domains?: string[];
    scenes?: string[];
    styles?: string[];
    routing_terms?: string[];
    auto_match?: boolean;
    auto_priority?: number;
    fallback?: boolean;
    allow_charts?: boolean;
    quality_status?: string;
  };
  is_default?: boolean;
};

export type TemplateList = {
  items: TemplateItem[];
  total: number;
};

export type StreamEvent =
  | { type: "status"; status: string }
  | { type: "chunk"; chunk: string }
  | { type: "slide_assets"; slide_index: number }
  | { type: "complete"; presentation: Presentation }
  | { type: "error"; detail: string };
