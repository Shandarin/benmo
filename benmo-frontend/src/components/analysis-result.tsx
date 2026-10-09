"use client";

import { useState } from "react";

import { AnalysisGraph } from "@/components/analysis-graph";
import { formatDate, humanize } from "@/lib/format";
import type { PublicAnalysisDetail } from "@/lib/schemas";

export function AnalysisResult({ detail }: { detail: PublicAnalysisDetail }) {
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const selected = detail.graph.edges.find((edge) => edge.id === selectedEdge);

  return (
    <>
      <section className="result-graph-section" aria-labelledby="causal-map-heading">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">Causal map</p>
            <h2 id="causal-map-heading">How the effects may propagate</h2>
          </div>
          <p>Select a connection to inspect its evidence.</p>
        </div>
        <AnalysisGraph
          nodes={detail.graph.nodes}
          edges={detail.graph.edges}
          onSelectEdge={setSelectedEdge}
        />
      </section>

      <section className="edge-narrative" aria-labelledby="chain-heading">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">Chain narrative</p>
            <h2 id="chain-heading">The argument, edge by edge</h2>
          </div>
          <p>{detail.graph.edges.length} causal connections evaluated</p>
        </div>
        <div className="edge-list">
          {detail.graph.edges.map((edge, index) => {
            const from = detail.graph.nodes.find((node) => node.id === edge.from_node_id);
            const to = detail.graph.nodes.find((node) => node.id === edge.to_node_id);
            const evidence = detail.evidence_by_edge[edge.id] ?? [];
            const verification = detail.verification_by_edge[edge.id];
            return (
              <article className="edge-article" id={`edge-${edge.id}`} key={edge.id}>
                <div className="edge-number">{String(index + 1).padStart(2, "0")}</div>
                <div className="edge-content">
                  <div className="edge-route">
                    <span>{from?.label ?? "Unknown cause"}</span>
                    <span aria-hidden="true">→</span>
                    <span>{to?.label ?? "Unknown effect"}</span>
                  </div>
                  <h3>{edge.mechanism}</h3>
                  <div className="edge-badges">
                    <span className={`grade grade-${edge.confidence_grade.toLowerCase()}`}>
                      Grade {edge.confidence_grade}
                    </span>
                    <span>{humanize(edge.evidence_status)}</span>
                    <span>{humanize(edge.outcome_status)}</span>
                  </div>
                  {edge.conditions.length ? (
                    <div className="conditions">
                      <h4>Conditions and invalidation tests</h4>
                      <ul>
                        {edge.conditions
                          .toSorted((a, b) => a.sort_order - b.sort_order)
                          .map((condition) => (
                            <li key={condition.id}>
                              <strong>{humanize(condition.kind)}:</strong> {condition.statement}
                            </li>
                          ))}
                      </ul>
                    </div>
                  ) : null}
                  <div className="evidence-grid">
                    {evidence.length ? (
                      evidence.map((item) => (
                        <figure className="evidence-quote" key={item.id}>
                          <blockquote>“{item.span.quoted_span}”</blockquote>
                          <figcaption>
                            <a
                              href={item.span.document.canonical_url ?? item.span.document.source_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {item.span.document.publisher ?? "Source document"}
                            </a>
                            <span>
                              Tier {item.span.document.source_tier} ·{" "}
                              {formatDate(item.span.document.published_at)}
                            </span>
                          </figcaption>
                          {item.span.limitations.length ? (
                            <p>Limitation: {item.span.limitations.join(" ")}</p>
                          ) : null}
                        </figure>
                      ))
                    ) : (
                      <p className="empty-note">No public evidence excerpt is attached to this edge.</p>
                    )}
                  </div>
                  {verification?.specs.length ? (
                    <div className="verification-block">
                      <h4>Pre-registered verification</h4>
                      {verification.specs.map((spec) => {
                        const latestRun = verification.runs.find(
                          (run) => run.verification_spec_id === spec.id,
                        );
                        return (
                          <div className="verification-row" key={spec.id}>
                            <div>
                              <strong>{spec.metric_code}</strong>
                              <span>
                                {humanize(spec.expected_direction)} · {spec.comparator_expression}
                              </span>
                            </div>
                            <span className="verification-status">
                              {latestRun ? humanize(latestRun.outcome_status) : "Awaiting observation"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {selected ? (
        <div className="edge-drawer" role="dialog" aria-modal="true" aria-label="Causal edge detail">
          <button type="button" onClick={() => setSelectedEdge(null)} aria-label="Close edge detail">
            ×
          </button>
          <p className="eyebrow">{humanize(selected.relation_type)}</p>
          <h2>{selected.mechanism}</h2>
          <p>
            Evidence status: <strong>{humanize(selected.evidence_status)}</strong>
          </p>
          <a href={`#edge-${selected.id}`} onClick={() => setSelectedEdge(null)}>
            Read the full argument
          </a>
        </div>
      ) : null}
    </>
  );
}
