import Link from "next/link";

import { AnalysisCard } from "@/components/analysis-card";
import { SubmissionForm } from "@/components/submission-form";
import { getPublicAnalyses } from "@/lib/api";

export default async function HomePage() {
  const latest = await getPublicAnalyses({ limit: 3 }).catch(() => []);
  return (
    <main>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Public causal research</p>
          <h1>Turn market events into claims that can be tested.</h1>
          <p className="hero-deck">
            Benmo traces how an event may propagate through companies, industries, and economic
            indicators—then shows the evidence, assumptions, and rules that could prove it wrong.
          </p>
          <div className="hero-proof">
            <div>
              <strong>Evidence first</strong>
              <span>Every material edge cites a source.</span>
            </div>
            <div>
              <strong>Falsifiable by design</strong>
              <span>Outcomes are tied to locked verification rules.</span>
            </div>
          </div>
        </div>
        <div className="hero-form" id="analyze">
          <div className="form-header">
            <span>01</span>
            <p>Start a public research request</p>
          </div>
          <SubmissionForm />
        </div>
      </section>

      <section className="method-strip" aria-label="How Benmo works">
        <p>From claim to public record</p>
        <ol>
          <li>
            <span>01</span>
            Normalize the event
          </li>
          <li>
            <span>02</span>
            Research each causal edge
          </li>
          <li>
            <span>03</span>
            Challenge the evidence
          </li>
          <li>
            <span>04</span>
            Publish or reject
          </li>
        </ol>
      </section>

      <section className="latest-section">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">The public record</p>
            <h2>Latest published analyses</h2>
          </div>
          <Link className="text-link" href="/explore">
            Explore all research →
          </Link>
        </div>
        {latest.length ? (
          <div className="card-grid">
            {latest.map((analysis) => (
              <AnalysisCard analysis={analysis} key={analysis.public_slug} />
            ))}
          </div>
        ) : (
          <div className="empty-publication">
            <p>No analyses have cleared the publication gate yet.</p>
            <span>The first evidence-backed result will appear here.</span>
          </div>
        )}
      </section>

      <section className="principles">
        <p className="eyebrow">Built for scrutiny</p>
        <div>
          <h2>Confidence is a conclusion, not a decoration.</h2>
          <p>
            Benmo keeps observed facts, proposed mechanisms, evidence snapshots, contradictory
            findings, and future verification separate. Weak links remain visible. Failed
            hypotheses stay out of the public index.
          </p>
          <Link className="text-link light" href="/methodology">
            Read the publication method →
          </Link>
        </div>
      </section>
    </main>
  );
}
