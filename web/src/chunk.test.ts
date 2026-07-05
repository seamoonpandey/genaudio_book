import { describe, expect, it } from "vitest";
import { chunkSentences } from "./chunk";

describe("chunkSentences", () => {
  it("packs sentences under limit", () => {
    const chunks = chunkSentences("One. Two. Three.", 12);
    expect(chunks).toEqual(["One. Two.", "Three."]);
  });
  it("hard-splits pathological runs", () => {
    const chunks = chunkSentences("x".repeat(950), 400);
    expect(chunks.length).toBe(3);
    expect(Math.max(...chunks.map((c) => c.length))).toBeLessThanOrEqual(400);
  });
  it("drops empty input", () => {
    expect(chunkSentences("   ", 400)).toEqual([]);
  });
});
