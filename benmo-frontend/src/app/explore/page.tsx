import type { Metadata } from "next";
import Link from "next/link";

import { AnalysisCard } from "@/components/analysis-card";
import { getPublicAnalyses } from "@/lib/api";

export const metadata: Metadata = {
  title: "Explore research",
  description: "Browse Benmo's published causal analyses.",
  alternates: { canonical: "/explore" },
};

export default async function ExplorePage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string; page?: string }>;
}) {
  const query = await searchParams;
  const page = Math.max(1, Number(query.page) || 1);
  const limit = 12;
  const analyses = await getPublicAnalyses({
    category: query.category,
    limit,
    offset: (page - 1) * limit,
  }).catch(() => []);
  return (
    <main className="page-shell">
      <header className="page-intro">
        <p className="eyebrow">Research archive</p>
        <h1>Published causal analyses</h1>
        <p>
          Every result here cleared a deterministic publication gate. Confidence grades describe
          the weakest supported connection in the chain.
        </p>
      </header>
      <form className="archive-filter" action="/explore">
        <label htmlFor="category">Filter by exact category</label>
        <div>
          <input
            id="category"
            name="category"
            defaultValue={query.category}
            placeholder="e.g. Energy"
          />
          <button type="submit">Apply filter</button>
          {query.category ? <Link href="/explore">Clear</Link> : null}
        </div>
      </form>
      {analyses.length ? (
        <div className="card-grid">
          {analyses.map((analysis) => (
            <AnalysisCard analysis={analysis} key={analysis.public_slug} />
          ))}
        </div>
      ) : (
        <div className="empty-publication">
          <p>No published analyses match this view.</p>
          <Link href="/#analyze">Start a new analysis</Link>
        </div>
      )}
      <nav className="pagination" aria-label="Research pages">
        {page > 1 ? <Link href={`/explore?page=${page - 1}`}>← Previous</Link> : <span />}
        {analyses.length === limit ? <Link href={`/explore?page=${page + 1}`}>Next →</Link> : null}
      </nav>
    </main>
  );
}
