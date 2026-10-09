import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AnalysisResult } from "@/components/analysis-result";
import { ApiError, getPublicAnalysis } from "@/lib/api";
import { formatDate, formatPercent } from "@/lib/format";

async function load(slug: string) {
  try {
    return await getPublicAnalysis(slug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ ref: string }>;
}): Promise<Metadata> {
  const { ref } = await params;
  const detail = await load(ref);
  const description = detail.summary.description.slice(0, 155);
  return {
    title: detail.summary.title,
    description,
    alternates: { canonical: `/analysis/${detail.summary.public_slug}` },
    openGraph: {
      type: "article",
      title: detail.summary.title,
      description,
      publishedTime: detail.summary.published_at,
      modifiedTime: detail.summary.updated_at,
      images: [
        {
          url: `/analysis/${detail.summary.public_slug}/og`,
          width: 1200,
          height: 630,
          alt: detail.summary.title,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: detail.summary.title,
      description,
      images: [`/analysis/${detail.summary.public_slug}/og`],
    },
  };
}

export default async function PublicAnalysisPage({
  params,
}: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = await params;
  const detail = await load(ref);
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: detail.summary.title,
    description: detail.summary.description,
    datePublished: detail.summary.published_at,
    dateModified: detail.summary.updated_at,
    author: { "@type": "Organization", name: "Benmo" },
    isAccessibleForFree: true,
    citation: Object.values(detail.evidence_by_edge)
      .flat()
      .map((item) => item.span.document.canonical_url ?? item.span.document.source_url),
  };
  return (
    <main className="result-page">
      <header className="result-header">
        <div className="result-meta">
          <span>{detail.summary.category ?? "Causal research"}</span>
          <span>Published {formatDate(detail.summary.published_at)}</span>
          <span>Version {detail.graph.version.version}</span>
        </div>
        <h1>{detail.summary.title}</h1>
        <p>{detail.summary.description}</p>
        <div className="result-scorecard">
          <div>
            <span>Weakest edge</span>
            <strong>{detail.summary.weakest_confidence_grade}</strong>
          </div>
          <div>
            <span>Chain confidence</span>
            <strong>{formatPercent(detail.summary.confidence_product)}</strong>
          </div>
          <div>
            <span>Causal edges</span>
            <strong>{detail.graph.edges.length}</strong>
          </div>
          <div>
            <span>Evidence excerpts</span>
            <strong>{Object.values(detail.evidence_by_edge).flat().length}</strong>
          </div>
        </div>
      </header>
      {detail.event.facts.length ? (
        <section className="facts-band" aria-label="Observed facts">
          <p>Observed facts</p>
          <div>
            {detail.event.facts.map((fact) => (
              <article key={fact.id}>
                <span>{fact.subject}</span>
                <strong>
                  {fact.observed_value ?? "—"} {fact.unit}
                </strong>
                <small>{fact.period}</small>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      <AnalysisResult detail={detail} />
      <aside className="research-disclaimer">
        <strong>Research note</strong>
        <p>
          This page records a causal hypothesis and its supporting evidence. It is not investment
          advice, and future verification may strengthen, weaken, or falsify individual edges.
        </p>
      </aside>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(articleJsonLd).replaceAll("<", "\\u003c"),
        }}
      />
    </main>
  );
}
