import assert from "node:assert/strict";
import test from "node:test";
import { versioned, type DeckDesignPlan } from "@sparkdeck/presentation-model";
import { resolveDesignTokens, validateTokens } from "./index.js";

test("semantic palette resolves readable page and accent text", () => {
  const plan: DeckDesignPlan = versioned({
    briefId: "brief",
    designSeed: "seed",
    tone: ["warm"],
    typography: { character: "friendly", headingFamily: "Microsoft YaHei", bodyFamily: "Microsoft YaHei", headingWeight: 700, bodyWeight: 400 },
    palette: { mood: "warm", background: "#FFF8EB", surface: "#FFFFFF", text: "#334155", primary: "#4F9C67", secondary: "#F28C45", accent: "#F2C94C", muted: "#CBD5E1" },
    shapeLanguage: { character: "soft", cornerStyle: "round", strokeStyle: "subtle", motif: "organic curves" },
    densityTarget: "airy",
    rhythm: { variation: "moderate", continuity: ["repeat color"] },
    consistencyRules: ["consistent type"]
  });
  assert.equal(validateTokens(resolveDesignTokens(plan)).passed, true);
});
