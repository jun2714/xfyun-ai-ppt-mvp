import type { DeckDesignPlan } from "@sparkdeck/presentation-model";

export type DesignTokens = {
  background: string;
  surface: string;
  text: string;
  textOnPrimary: string;
  primary: string;
  secondary: string;
  accent: string;
  muted: string;
  headingFontFamily: string;
  bodyFontFamily: string;
  headingWeight: number;
  bodyWeight: number;
  deckTitlePt: number;
  titlePt: number;
  bodyPt: number;
  captionPt: number;
  lineHeight: number;
  space: number;
  safeInset: number;
  radius: number;
  strokeWidth: number;
  motif: string;
};

const channel = (value: number) => value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
const luminance = (hex: string) => {
  const rgb = [1, 3, 5].map((index) => channel(Number.parseInt(hex.slice(index, index + 2), 16) / 255));
  return 0.2126 * rgb[0]! + 0.7152 * rgb[1]! + 0.0722 * rgb[2]!;
};
export const contrast = (left: string, right: string) => {
  const [high, low] = [luminance(left), luminance(right)].sort((a, b) => b - a);
  return (high! + 0.05) / (low! + 0.05);
};
export const readableText = (background: string, preferred: string) => {
  const choices = [preferred, "#111111", "#FFFFFF"];
  return choices.sort((a, b) => contrast(b, background) - contrast(a, background))[0]!;
};

export function resolveDesignTokens(plan: DeckDesignPlan): DesignTokens {
  const density = plan.densityTarget;
  const titlePt = density === "dense" ? 34 : density === "airy" ? 42 : 38;
  const bodyPt = density === "dense" ? 18 : density === "airy" ? 22 : 20;
  return {
    background: plan.palette.background,
    surface: plan.palette.surface,
    text: readableText(plan.palette.background, plan.palette.text),
    textOnPrimary: readableText(plan.palette.primary, plan.palette.background),
    primary: plan.palette.primary,
    secondary: plan.palette.secondary,
    accent: plan.palette.accent,
    muted: plan.palette.muted,
    headingFontFamily: plan.typography.headingFamily,
    bodyFontFamily: plan.typography.bodyFamily,
    headingWeight: plan.typography.headingWeight,
    bodyWeight: plan.typography.bodyWeight,
    deckTitlePt: titlePt + 16,
    titlePt,
    bodyPt,
    captionPt: 16,
    lineHeight: 1.2,
    space: density === "airy" ? 24 : density === "dense" ? 12 : 18,
    safeInset: density === "dense" ? 34 : 42,
    radius: plan.shapeLanguage.cornerStyle === "round" ? 24 : plan.shapeLanguage.cornerStyle === "soft" ? 10 : 0,
    strokeWidth: plan.shapeLanguage.strokeStyle === "expressive" ? 3 : plan.shapeLanguage.strokeStyle === "subtle" ? 1 : 0,
    motif: plan.shapeLanguage.motif
  };
}

export function validateTokens(tokens: DesignTokens) {
  const pageContrast = contrast(tokens.text, tokens.background);
  const primaryContrast = contrast(tokens.textOnPrimary, tokens.primary);
  return {
    passed: pageContrast >= 4.5 && primaryContrast >= 4.5 && tokens.bodyPt >= 16,
    pageContrast,
    primaryContrast
  };
}
