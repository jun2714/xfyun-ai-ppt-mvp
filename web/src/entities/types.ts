export type SlideOutline = {
  content: string;
  content_contract?: Record<string, unknown> | null;
};

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
  generation_metadata?: {
    outline_status?: "pending" | "ready";
    selected_template?: string | null;
    visual_mode?: "template" | "ai-background";
  } | null;
};

export type TemplateItem = {
  id: string;
  name: string;
  description?: string | null;
  layout_count: number;
  thumbnail?: string | null;
  is_default?: boolean;
};

export type TemplateList = {
  items: TemplateItem[];
  total: number;
};

export type StreamEvent =
  | { type: "status"; status: string }
  | { type: "chunk"; chunk: string }
  | { type: "kindergarten_chunk"; chunk: string }
  | { type: "outline"; outline: PresentationOutline }
  | { type: "slide_assets"; slide_index: number }
  | { type: "complete"; presentation: Presentation }
  | { type: "error"; detail: string };
