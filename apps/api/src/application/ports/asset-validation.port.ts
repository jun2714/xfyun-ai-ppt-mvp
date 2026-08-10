import type { MediaRole } from "@sparkdeck/presentation-model";

export type AssetValidationInput = {
  url?: string;
  base64?: string;
  role: MediaRole;
  targetAspectRatio: number;
  incurredCost?: boolean;
};

export type ValidatedAsset = {
  /** Normalized bytes make preview and PPTX export consume exactly the same artifact. */
  base64: string;
  width: number;
  height: number;
  hasMeaningfulTransparency: boolean;
};

/** Decodes and validates provider output before it can enter project state or cache. */
export interface AssetValidationPort {
  validate(input: AssetValidationInput): Promise<ValidatedAsset>;
}
