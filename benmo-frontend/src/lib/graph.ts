import dagre from "@dagrejs/dagre";
import { MarkerType, Position, type Edge, type Node } from "@xyflow/react";

import type { PublicEdge, PublicNode } from "@/lib/schemas";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 88;

export function layoutGraph(nodes: PublicNode[], edges: PublicEdge[]): {
  nodes: Node[];
  edges: Edge[];
} {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", ranksep: 90, nodesep: 44, marginx: 28, marginy: 28 });

  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((edge) => graph.setEdge(edge.from_node_id, edge.to_node_id));
  dagre.layout(graph);

  return {
    nodes: nodes.map((node) => {
      const position = graph.node(node.id);
      return {
        id: node.id,
        position: {
          x: position.x - NODE_WIDTH / 2,
          y: position.y - NODE_HEIGHT / 2,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: { label: node.label, type: node.node_type },
        type: "benmo",
      };
    }),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.from_node_id,
      target: edge.to_node_id,
      label: edge.relation_type.replaceAll("_", " "),
      markerEnd: { type: MarkerType.ArrowClosed },
      data: { confidence: edge.confidence_grade },
      style: { strokeWidth: edge.is_critical ? 2.5 : 1.7 },
    })),
  };
}
