import {
  analysisReadSchema,
  publicAnalysisDetailSchema,
  publicAnalysisSummarySchema,
  type AnalysisRead,
  type PublicAnalysisDetail,
  type PublicAnalysisSummary,
} from "@/lib/schemas";

const apiBaseUrl = () => process.env.BENMO_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(`The Benmo API returned ${response.status}.`, response.status);
  }
  return response.json();
}

export async function getPublicAnalyses(options?: {
  category?: string;
  limit?: number;
  offset?: number;
}): Promise<PublicAnalysisSummary[]> {
  const search = new URLSearchParams();
  if (options?.category) search.set("category", options.category);
  search.set("limit", String(options?.limit ?? 20));
  search.set("offset", String(options?.offset ?? 0));
  const data = await getJson(`/v1/public/analyses?${search}`);
  return publicAnalysisSummarySchema.array().parse(data);
}

export async function getPublicAnalysis(slug: string): Promise<PublicAnalysisDetail> {
  const data = await getJson(`/v1/public/analyses/${encodeURIComponent(slug)}`);
  return publicAnalysisDetailSchema.parse(data);
}

export async function getAnalysis(id: string): Promise<AnalysisRead> {
  const data = await getJson(`/v1/analyses/${encodeURIComponent(id)}`);
  return analysisReadSchema.parse(data);
}
