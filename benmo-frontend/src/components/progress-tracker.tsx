"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { analysisReadSchema, type AnalysisRead } from "@/lib/schemas";

type ProgressItem = {
  sequence: number;
  message: string;
  created_at: string;
};

const EVENT_NAMES = [
  "analysis.queued",
  "analysis.progress",
  "analysis.completed",
  "analysis.failed",
  "analysis.enqueue_failed",
  "analysis.review_decided",
];

export function ProgressTracker({ initial }: { initial: AnalysisRead }) {
  const router = useRouter();
  const [analysis, setAnalysis] = useState(initial);
  const [events, setEvents] = useState<ProgressItem[]>([]);
  const [connection, setConnection] = useState<"live" | "reconnecting">("reconnecting");

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const response = await fetch(`/v1/analyses/${analysis.id}`, { cache: "no-store" });
        if (!response.ok) return;
        const next = analysisReadSchema.parse(await response.json());
        if (!active) return;
        setAnalysis(next);
        if (next.status === "published") router.replace(`/analysis/${next.public_slug}`);
      } catch {
        setConnection("reconnecting");
      }
    }

    void refresh();
    const polling = window.setInterval(refresh, 5000);
    const stream = new EventSource(`/v1/analyses/${analysis.id}/events`);
    stream.onopen = () => setConnection("live");
    stream.onerror = () => setConnection("reconnecting");
    const receive = (raw: Event) => {
      const event = raw as MessageEvent<string>;
      try {
        const payload = JSON.parse(event.data) as ProgressItem;
        if (payload.sequence) {
          setEvents((current) => {
            if (current.some((item) => item.sequence === payload.sequence)) return current;
            return [...current, payload].toSorted((a, b) => a.sequence - b.sequence);
          });
        }
        void refresh();
      } catch {
        void refresh();
      }
    };
    EVENT_NAMES.forEach((name) => stream.addEventListener(name, receive));
    stream.addEventListener("end", receive);
    return () => {
      active = false;
      window.clearInterval(polling);
      stream.close();
    };
  }, [analysis.id, router]);

  const waitingReview = analysis.status === "review_required";
  const failed = analysis.status === "failed" || analysis.status === "rejected";

  return (
    <main className="progress-page">
      <div className="progress-kicker">
        <span className={`live-dot ${connection}`} />
        {connection === "live" ? "Live research feed" : "Reconnecting · status checks remain active"}
      </div>
      <p className="eyebrow">Analysis in progress</p>
      <h1>{waitingReview ? "Research complete. Review pending." : "Building the causal record."}</h1>
      <p className="progress-prompt">{analysis.input_text}</p>
      <div className="progress-meter" aria-label={`${analysis.progress_percent}% complete`}>
        <div style={{ width: `${analysis.progress_percent}%` }} />
      </div>
      <div className="progress-stats">
        <span>{analysis.progress_percent}%</span>
        <span>{analysis.current_stage.replaceAll("_", " ")}</span>
        <span>{analysis.status.replaceAll("_", " ")}</span>
      </div>

      {waitingReview ? (
        <aside className="status-callout">
          A publication gate flagged this result for human review. Keep this private link; the page
          will update automatically after a decision.
        </aside>
      ) : null}
      {failed ? (
        <aside className="status-callout error">
          <strong>{analysis.status === "rejected" ? "Not published." : "Analysis failed."}</strong>
          <span>{analysis.error_message ?? "The result did not meet the publication criteria."}</span>
        </aside>
      ) : null}

      <section className="timeline" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">Research log</h2>
        <ol>
          {(events.length
            ? events
            : [
                {
                  sequence: 1,
                  message: "Analysis request accepted and queued.",
                  created_at: analysis.created_at,
                },
              ]
          ).map((item) => (
            <li key={item.sequence}>
              <span>{item.sequence}</span>
              <div>
                <strong>{item.message}</strong>
                <time>{new Date(item.created_at).toLocaleTimeString()}</time>
              </div>
            </li>
          ))}
        </ol>
      </section>
      <p className="progress-note">
        You can safely close this tab and return with the same URL. Research may take several
        minutes.
      </p>
    </main>
  );
}
