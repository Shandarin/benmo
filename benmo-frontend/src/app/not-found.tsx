import Link from "next/link";

export default function NotFound() {
  return (
    <main className="not-found">
      <p className="eyebrow">404 · Record not found</p>
      <h1>This analysis is not public.</h1>
      <p>It may still be running, awaiting review, rejected, or the URL may be incorrect.</p>
      <Link className="primary-button" href="/explore">
        Explore published research
      </Link>
    </main>
  );
}
