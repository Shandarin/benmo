import type { MetadataRoute } from "next";

import { getPublicAnalyses } from "@/lib/api";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const siteUrl = process.env.SITE_URL ?? "http://localhost:3000";
  const analyses = [];
  for (let offset = 0; ; offset += 100) {
    const page = await getPublicAnalyses({ limit: 100, offset }).catch(() => []);
    analyses.push(...page);
    if (page.length < 100) break;
  }
  return [
    { url: siteUrl, changeFrequency: "daily", priority: 1 },
    { url: `${siteUrl}/explore`, changeFrequency: "daily", priority: 0.8 },
    { url: `${siteUrl}/methodology`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${siteUrl}/about`, changeFrequency: "monthly", priority: 0.5 },
    ...analyses.map((analysis) => ({
      url: `${siteUrl}/analysis/${analysis.public_slug}`,
      lastModified: new Date(analysis.updated_at),
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
  ];
}
