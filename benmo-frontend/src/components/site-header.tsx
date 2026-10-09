import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="wordmark" href="/" aria-label="Benmo home">
        <span className="wordmark-mark" aria-hidden="true">
          B
        </span>
        <span>BENMO</span>
      </Link>
      <nav className="site-nav" aria-label="Primary navigation">
        <Link href="/explore">Explore</Link>
        <Link href="/methodology">Methodology</Link>
        <Link href="/about">About</Link>
      </nav>
      <Link className="header-cta" href="/#analyze">
        Start an analysis
      </Link>
    </header>
  );
}
