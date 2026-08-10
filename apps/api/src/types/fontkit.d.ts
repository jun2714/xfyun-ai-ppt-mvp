declare module "fontkit" {
  export type Font = {
    familyName?: string;
    subfamilyName?: string;
    postscriptName?: string;
    unitsPerEm: number;
    layout(text: string): { positions: Array<{ xAdvance: number }> };
  };
  export type FontCollection = { fonts: Font[] };
  export function openSync(path: string): Font | FontCollection;
}
