"use client";

import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type NodeProps,
} from "@xyflow/react";
import { useMemo } from "react";

import { humanize } from "@/lib/format";
import { layoutGraph } from "@/lib/graph";
import type { PublicEdge, PublicNode } from "@/lib/schemas";

function BenmoNode({ data }: NodeProps) {
  const value = data as { label: string; type: string };
  return (
    <div className="graph-node">
      <Handle type="target" position={Position.Left} />
      <span>{humanize(value.type)}</span>
      <strong>{value.label}</strong>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export function AnalysisGraph({
  nodes,
  edges,
  onSelectEdge,
}: {
  nodes: PublicNode[];
  edges: PublicEdge[];
  onSelectEdge?: (edgeId: string) => void;
}) {
  const layout = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const nodeTypes = useMemo(() => ({ benmo: BenmoNode }), []);

  return (
    <div className="graph-shell" aria-label="Interactive causal chain diagram">
      <ReactFlow
        nodes={layout.nodes}
        edges={layout.edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.35}
        maxZoom={1.7}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        onEdgeClick={(_, edge) => onSelectEdge?.(edge.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#d7d0c4" gap={24} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor="#173a48" maskColor="rgba(247, 243, 235, .78)" />
      </ReactFlow>
    </div>
  );
}
