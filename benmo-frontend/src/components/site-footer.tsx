import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div>
        <p className="footer-brand">BENMO</p>
        <p>Public causal research, built to be challenged.</p>
      </div>
      <div className="footer-links">
        <Link href="/explore">Research</Link>
        <Link href="/methodology">Methodology</Link>
        <Link href="/about">About</Link>
      </div>
      <p className="footer-note">
        Benmo publishes research hypotheses, not investment advice.
      </p>
    </footer>
  );
}
