"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useSyncExternalStore } from "react";

import { analysisAcceptedSchema } from "@/lib/schemas";

const EXAMPLE =
  "Oil prices rose sharply after new shipping restrictions. Which airline costs and margins could be affected over the next two quarters?";

export function SubmissionForm() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const requestRef = useRef<{ input: string; key: string } | null>(null);
  const hydrated = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = input.trim();
    if (normalized.length < 10) {
      setError("Describe the event or claim in at least 10 characters.");
      return;
    }
    setPending(true);
    setError(null);
    const key =
      requestRef.current?.input === normalized ? requestRef.current.key : crypto.randomUUID();
    requestRef.current = { input: normalized, key };
    sessionStorage.setItem("benmo:last-idempotency-key", key);
    try {
      const response = await fetch("/v1/analyses", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": key,
        },
        body: JSON.stringify({
          input_text: normalized,
          context: { locale: "en-US" },
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const apiMessage = body?.error?.message as string | undefined;
        if (response.status === 403 || response.status === 429) {
          throw new Error("Too many analyses were submitted from this network. Try again shortly.");
        }
        if (response.status === 422) {
          throw new Error(apiMessage ?? "Check the analysis prompt and try again.");
        }
        if (response.status === 409) {
          throw new Error("This request conflicted with an earlier submission. Please submit again.");
        }
        if (response.status === 503) {
          throw new Error("The research queue is temporarily unavailable. Please retry in a moment.");
        }
        throw new Error(apiMessage ?? "Benmo could not start this analysis.");
      }
      const accepted = analysisAcceptedSchema.parse(await response.json());
      requestRef.current = null;
      router.push(`/analysis/${accepted.analysis_id}/progress`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "A network error interrupted the request.");
      setPending(false);
    }
  }

  return (
    <form className="submission-form" onSubmit={submit}>
      <label htmlFor="analysis-input">What event or claim should Benmo investigate?</label>
      <textarea
        id="analysis-input"
        value={input}
        onChange={(event) => setInput(event.target.value)}
        minLength={10}
        maxLength={10000}
        rows={6}
        placeholder="Describe a specific event and the downstream effects you want to understand…"
        aria-describedby="analysis-help analysis-error"
      />
      <div className="form-tools">
        <button className="example-button" type="button" onClick={() => setInput(EXAMPLE)}>
          Use an example
        </button>
        <span id="analysis-help">{input.length.toLocaleString()} / 10,000</span>
      </div>
      {error ? (
        <p className="form-error" id="analysis-error" role="alert">
          {error}
        </p>
      ) : null}
      <button className="primary-button" type="submit" disabled={pending || !hydrated}>
        {pending ? "Starting research…" : hydrated ? "Map the causal chain" : "Preparing form…"}
        <span aria-hidden="true">→</span>
      </button>
      <p className="form-disclaimer">
        Submissions may become public only after passing Benmo&apos;s publication gate. Do not
        include confidential information.
      </p>
    </form>
  );
}
