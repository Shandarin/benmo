import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Methodology",
  description: "How Benmo researches, challenges, grades, and publishes causal hypotheses.",
  alternates: { canonical: "/methodology" },
};

const stages = [
  ["Normalize", "Separate observed facts from claims, define the event, and preserve uncertainty."],
  ["Map", "Propose explicit causal edges, mechanisms, conditions, and invalidation tests."],
  ["Research", "Collect source snapshots and attach evidence to the precise claim it supports."],
  ["Challenge", "Search for contradictory evidence and test whether citations entail each claim."],
  ["Pre-register", "Lock metrics, baselines, thresholds, and observation windows before outcomes occur."],
  ["Publish", "Apply deterministic gates. Unsupported or materially contested chains stay private."],
];

export default function MethodologyPage() {
  return (
    <main className="page-shell prose-page">
      <header className="page-intro">
        <p className="eyebrow">Methodology</p>
        <h1>A claim should show how it could be wrong.</h1>
        <p>
          Benmo treats causal analysis as a versioned public record: sources can expire, outcomes
          can change, and confidence must remain traceable to individual connections.
        </p>
      </header>
      <section className="methodology-grid">
        {stages.map(([title, text], index) => (
          <article key={title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <h2>{title}</h2>
            <p>{text}</p>
          </article>
        ))}
      </section>
      <section className="grade-table">
        <p className="eyebrow">Confidence grades</p>
        <h2>The chain inherits its weakest material edge.</h2>
        <div>
          <article>
            <strong>A</strong>
            <p>Direct, high-quality evidence with an executable verification rule.</p>
          </article>
          <article>
            <strong>B</strong>
            <p>Good evidence with a meaningful limitation, indirect step, or narrower scope.</p>
          </article>
          <article>
            <strong>C</strong>
            <p>Plausible but materially limited evidence; use as a monitored hypothesis.</p>
          </article>
          <article>
            <strong>Insufficient</strong>
            <p>The record cannot support publication as a causal conclusion.</p>
          </article>
        </div>
      </section>
    </main>
  );
}
