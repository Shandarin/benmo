import { describe, expect, it } from "vitest";

import { layoutGraph } from "./graph";
import type { PublicEdge, PublicNode } from "./schemas";

describe("layoutGraph", () => {
  it("lays causes to the left of their effects", () => {
    const nodes = [
      { id: "a", label: "Cause", node_type: "event" },
      { id: "b", label: "Effect", node_type: "metric" },
    ] as PublicNode[];
    const edges = [
      {
        id: "e",
        from_node_id: "a",
        to_node_id: "b",
        relation_type: "input_cost",
        confidence_grade: "A",
        is_critical: false,
      },
    ] as PublicEdge[];
    const result = layoutGraph(nodes, edges);
    expect(result.nodes.find((node) => node.id === "a")!.position.x).toBeLessThan(
      result.nodes.find((node) => node.id === "b")!.position.x,
    );
    expect(result.edges[0]).toMatchObject({ source: "a", target: "b" });
  });
});
