import { ImageResponse } from "next/og";

import { getPublicAnalysis } from "@/lib/api";

const size = { width: 1200, height: 630 };

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ ref: string }> },
) {
  const { ref } = await params;
  const detail = await getPublicAnalysis(ref);
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        width: "100%",
        height: "100%",
        padding: "68px 76px",
        color: "#f8f3ea",
        background: "#08232d",
        fontFamily: "Georgia, serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 58,
            height: 58,
            color: "#b96036",
            border: "2px solid #b96036",
            borderRadius: "50%",
            fontSize: 36,
          }}
        >
          B
        </div>
        <div
          style={{
            color: "#d88760",
            fontFamily: "Arial, sans-serif",
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "0.24em",
          }}
        >
          BENMO
        </div>
      </div>
      <div style={{ display: "flex", maxWidth: 980, fontSize: 66, lineHeight: 1.05 }}>
        {detail.summary.title}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          paddingTop: 24,
          color: "#afbdaf",
          borderTop: "2px solid #b96036",
          fontFamily: "Arial, sans-serif",
          fontSize: 21,
          letterSpacing: "0.06em",
        }}
      >
        <span>PUBLIC CAUSAL RESEARCH</span>
        <span>
          GRADE {detail.summary.weakest_confidence_grade} · {detail.graph.edges.length} CAUSAL EDGES
        </span>
      </div>
    </div>,
    size,
  );
}
