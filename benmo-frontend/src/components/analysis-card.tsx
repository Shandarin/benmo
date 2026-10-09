import Link from "next/link";

import { formatDate, formatPercent } from "@/lib/format";
import type { PublicAnalysisSummary } from "@/lib/schemas";

export function AnalysisCard({ analysis }: { analysis: PublicAnalysisSummary }) {
  return (
    <article className="analysis-card">
      <div className="card-meta">
        <span>{analysis.category ?? "Causal research"}</span>
        <span>{formatDate(analysis.published_at)}</span>
      </div>
      <h3>
        <Link href={`/analysis/${analysis.public_slug}`}>{analysis.title}</Link>
      </h3>
      <p>{analysis.description}</p>
      <div className="card-footer">
        <span className={`grade grade-${analysis.weakest_confidence_grade.toLowerCase()}`}>
          Grade {analysis.weakest_confidence_grade}
        </span>
        <span>Chain confidence {formatPercent(analysis.confidence_product)}</span>
      </div>
    </article>
  );
}
