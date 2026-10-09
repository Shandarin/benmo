import http from "node:http";

const analysisId = "11111111-1111-4111-8111-111111111111";
const slug = "ana_mock_public";
let statusReads = 0;
const now = "2026-07-30T00:00:00Z";

const summary = {
  public_slug: slug,
  title: "Oil prices increased materially.",
  description: "Higher unhedged jet fuel prices may compress airline operating margins.",
  category: "Energy",
  occurred_at: now,
  weakest_confidence_grade: "A",
  confidence_product: "0.92",
  published_at: now,
  updated_at: now,
};

const detail = {
  summary,
  event: {
    id: "event-1",
    title: summary.title,
    description: summary.description,
    category: "Energy",
    occurred_at: now,
    status: "verified",
    created_at: now,
    updated_at: now,
    facts: [],
  },
  graph: {
    chain: {
      id: "chain-1",
      event_id: "event-1",
      title: summary.title,
      slug: "oil-airlines",
      status: "published",
      current_version_id: "version-1",
      weakest_confidence_grade: "A",
      confidence_product: "0.92",
      published_at: now,
      created_at: now,
      updated_at: now,
    },
    version: {
      id: "version-1",
      chain_id: "chain-1",
      version: 1,
      status: "published",
      created_at: now,
      published_at: now,
    },
    nodes: [
      {
        id: "node-1",
        chain_version_id: "version-1",
        key: "oil",
        node_type: "commodity",
        label: "Jet fuel price rises",
        metric_code: null,
        entity_ref: null,
        attributes: {},
      },
      {
        id: "node-2",
        chain_version_id: "version-1",
        key: "margin",
        node_type: "company_metric",
        label: "Airline margins compress",
        metric_code: null,
        entity_ref: null,
        attributes: {},
      },
    ],
    edges: [
      {
        id: "edge-1",
        chain_version_id: "version-1",
        from_node_id: "node-1",
        to_node_id: "node-2",
        relation_type: "input_cost",
        direction: "positive",
        mechanism: "Higher unhedged fuel prices increase operating expense.",
        evidence_status: "supported",
        outcome_status: "monitoring",
        confidence_grade: "A",
        confidence_score: "0.95",
        confidence_breakdown: {},
        is_critical: true,
        conditions: [],
        verification_specs: [],
      },
    ],
  },
  evidence_by_edge: { "edge-1": [] },
  verification_by_edge: { "edge-1": { edge_id: "edge-1", specs: [], runs: [] } },
};

function json(response, code, body) {
  response.writeHead(code, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

http
  .createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1:4010");
    if (url.pathname === "/health/ready") return json(response, 200, { status: "ok" });
    if (request.method === "POST" && url.pathname === "/v1/analyses") {
      statusReads = 0;
      return json(response, 202, {
        analysis_id: analysisId,
        status: "queued",
        public_url: `/analysis/${slug}`,
      });
    }
    if (url.pathname === `/v1/analyses/${analysisId}/events`) {
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      setTimeout(() => {
        response.write(
          `id: 2\nevent: analysis.progress\ndata: ${JSON.stringify({
            sequence: 2,
            message: "Checking primary sources.",
            created_at: now,
          })}\n\n`,
        );
      }, 600);
      setTimeout(() => {
        response.write(`event: end\ndata: ${JSON.stringify({ status: "published" })}\n\n`);
        response.end();
      }, 1000);
      return;
    }
    if (url.pathname === `/v1/analyses/${analysisId}`) {
      statusReads += 1;
      return json(response, 200, {
        id: analysisId,
        event_id: statusReads > 2 ? "22222222-2222-4222-8222-222222222222" : null,
        input_text: "Oil prices rose sharply. Which airline margins could be affected?",
        input_context: { locale: "en-US" },
        status: statusReads > 2 ? "published" : "running",
        current_stage: statusReads > 2 ? "completed" : "evidence_research",
        progress_percent: statusReads > 2 ? 100 : 42,
        public_slug: slug,
        error_code: null,
        error_message: null,
        created_at: now,
        updated_at: now,
        completed_at: statusReads > 2 ? now : null,
      });
    }
    if (url.pathname === `/v1/public/analyses/${slug}`) return json(response, 200, detail);
    if (url.pathname === "/v1/public/analyses") return json(response, 200, [summary]);
    return json(response, 404, { error: { message: "Not found" } });
  })
  .listen(4010, "127.0.0.1");
