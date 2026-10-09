import { z } from "zod";

const dateString = z.string();
const nullableDate = dateString.nullable();
const decimal = z.union([z.string(), z.number()]).nullable();

export const analysisAcceptedSchema = z.object({
  analysis_id: z.string().uuid(),
  status: z.string(),
  public_url: z.string(),
});

export const analysisReadSchema = z.object({
  id: z.string().uuid(),
  event_id: z.string().uuid().nullable(),
  input_text: z.string(),
  input_context: z.record(z.string(), z.unknown()),
  status: z.enum(["queued", "running", "review_required", "published", "rejected", "failed"]),
  current_stage: z.string(),
  progress_percent: z.number(),
  public_slug: z.string(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  created_at: dateString,
  updated_at: dateString,
  completed_at: nullableDate,
});

export const publicAnalysisSummarySchema = z.object({
  public_slug: z.string(),
  title: z.string(),
  description: z.string(),
  category: z.string().nullable(),
  occurred_at: nullableDate,
  weakest_confidence_grade: z.enum(["A", "B", "C", "Insufficient"]),
  confidence_product: decimal,
  published_at: dateString,
  updated_at: dateString,
});

const factSchema = z.object({
  id: z.string(),
  subject: z.string(),
  metric_code: z.string().nullable(),
  observed_value: decimal,
  unit: z.string().nullable(),
  period: z.string().nullable(),
  fact_status: z.string(),
  source_document_id: z.string().nullable(),
  as_of: nullableDate,
  details: z.record(z.string(), z.unknown()),
});

const eventSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  category: z.string().nullable(),
  occurred_at: nullableDate,
  status: z.string(),
  created_at: dateString,
  updated_at: dateString,
  facts: z.array(factSchema),
});

const nodeSchema = z.object({
  id: z.string(),
  chain_version_id: z.string(),
  key: z.string(),
  node_type: z.string(),
  label: z.string(),
  metric_code: z.string().nullable(),
  entity_ref: z.string().nullable(),
  attributes: z.record(z.string(), z.unknown()),
});

const conditionSchema = z.object({
  id: z.string(),
  kind: z.string(),
  statement: z.string(),
  sort_order: z.number(),
});

const verificationSpecSchema = z.object({
  id: z.string(),
  edge_id: z.string(),
  metric_code: z.string(),
  source_adapter: z.string(),
  expected_direction: z.string(),
  threshold: z.record(z.string(), z.unknown()),
  baseline_rule: z.record(z.string(), z.unknown()),
  observation_window: z.record(z.string(), z.unknown()),
  comparator_expression: z.string(),
  spec_version: z.number(),
  supersedes_id: z.string().nullable(),
  locked_at: dateString,
  created_at: dateString,
});

const edgeSchema = z.object({
  id: z.string(),
  chain_version_id: z.string(),
  from_node_id: z.string(),
  to_node_id: z.string(),
  relation_type: z.string(),
  direction: z.string(),
  mechanism: z.string(),
  evidence_status: z.string(),
  outcome_status: z.string(),
  confidence_grade: z.string(),
  confidence_score: decimal,
  confidence_breakdown: z.record(z.string(), z.unknown()),
  is_critical: z.boolean(),
  conditions: z.array(conditionSchema),
  verification_specs: z.array(verificationSpecSchema),
});

const chainSchema = z.object({
  id: z.string(),
  event_id: z.string(),
  title: z.string(),
  slug: z.string(),
  status: z.string(),
  current_version_id: z.string().nullable(),
  weakest_confidence_grade: z.string(),
  confidence_product: decimal,
  published_at: nullableDate,
  created_at: dateString,
  updated_at: dateString,
});

const evidenceDocumentSchema = z.object({
  id: z.string(),
  source_url: z.string(),
  canonical_url: z.string().nullable(),
  source_type: z.string(),
  source_tier: z.enum(["A", "B", "C", "D"]),
  publisher: z.string().nullable(),
  published_at: nullableDate,
  retrieved_at: dateString,
  content_type: z.string().nullable(),
  is_accessible: z.boolean(),
});

const edgeEvidenceSchema = z.object({
  id: z.string(),
  edge_id: z.string(),
  role: z.string(),
  entailment_status: z.string(),
  is_direct: z.boolean(),
  independent_source_key: z.string().nullable(),
  contradiction_level: z.string(),
  span: z.object({
    id: z.string(),
    document_id: z.string(),
    quoted_span: z.string(),
    supported_claim: z.string(),
    support_level: z.string(),
    limitations: z.array(z.string()),
    quote_verified: z.boolean(),
    verified_at: nullableDate,
    document: evidenceDocumentSchema,
  }),
});

const verificationRunSchema = z.object({
  id: z.string(),
  verification_spec_id: z.string(),
  scheduled_for: nullableDate,
  started_at: nullableDate,
  completed_at: nullableDate,
  outcome_status: z.string(),
  observed_value: decimal,
  baseline_value: decimal,
  change_pct: decimal,
  threshold_pct: decimal,
  evaluated_by: z.string().nullable(),
  result: z.record(z.string(), z.unknown()),
  error_message: z.string().nullable(),
  created_at: dateString,
});

export const publicAnalysisDetailSchema = z.object({
  summary: publicAnalysisSummarySchema,
  event: eventSchema,
  graph: z.object({
    chain: chainSchema,
    version: z.object({
      id: z.string(),
      chain_id: z.string(),
      version: z.number(),
      status: z.string(),
      created_at: dateString,
      published_at: nullableDate,
    }),
    nodes: z.array(nodeSchema),
    edges: z.array(edgeSchema),
  }),
  evidence_by_edge: z.record(z.string(), z.array(edgeEvidenceSchema)),
  verification_by_edge: z.record(
    z.string(),
    z.object({
      edge_id: z.string(),
      specs: z.array(verificationSpecSchema),
      runs: z.array(verificationRunSchema),
    }),
  ),
});

export type AnalysisAccepted = z.infer<typeof analysisAcceptedSchema>;
export type AnalysisRead = z.infer<typeof analysisReadSchema>;
export type PublicAnalysisSummary = z.infer<typeof publicAnalysisSummarySchema>;
export type PublicAnalysisDetail = z.infer<typeof publicAnalysisDetailSchema>;
export type PublicNode = PublicAnalysisDetail["graph"]["nodes"][number];
export type PublicEdge = PublicAnalysisDetail["graph"]["edges"][number];
