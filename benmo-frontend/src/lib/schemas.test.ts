import { describe, expect, it } from "vitest";

import { analysisAcceptedSchema, publicAnalysisSummarySchema } from "./schemas";

describe("API schemas", () => {
  it("accepts the analysis submission contract", () => {
    expect(
      analysisAcceptedSchema.parse({
        analysis_id: "1ca5dd6c-a666-43b4-8412-25da2051d7fb",
        status: "queued",
        public_url: "/analysis/ana_123",
      }).status,
    ).toBe("queued");
  });

  it("rejects an unsafe incomplete public summary", () => {
    expect(() => publicAnalysisSummarySchema.parse({ public_slug: "ana_123" })).toThrow();
  });
});
