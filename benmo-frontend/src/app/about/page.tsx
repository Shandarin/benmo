import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About",
  description: "Why Benmo is building a public, continuously verified causal research record.",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <main className="page-shell prose-page">
      <header className="page-intro">
        <p className="eyebrow">About Benmo</p>
        <h1>Markets remember predictions. They rarely preserve the reasoning.</h1>
        <p>
          Benmo exists to make the reasoning inspectable: what happened, which downstream effects
          were proposed, what evidence supported them, and which future observation would count as
          a failure.
        </p>
      </header>
      <section className="about-manifesto">
        <div>
          <span>01</span>
          <h2>Public by merit</h2>
          <p>
            A submission is not automatically a publication. It must clear evidence, entailment,
            contradiction, and verification gates.
          </p>
        </div>
        <div>
          <span>02</span>
          <h2>Specific over certain</h2>
          <p>
            We prefer a narrow mechanism with explicit conditions to a sweeping narrative that
            cannot be tested.
          </p>
        </div>
        <div>
          <span>03</span>
          <h2>Designed to change</h2>
          <p>
            Evidence and outcomes evolve. Benmo keeps versions so a conclusion can be revisited
            without rewriting its history.
          </p>
        </div>
      </section>
    </main>
  );
}
