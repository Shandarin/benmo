import type { Metadata } from "next";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";
import "@xyflow/react/dist/style.css";

const siteUrl = process.env.SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Benmo — Public causal research",
    template: "%s | Benmo",
  },
  description:
    "Trace market events through evidence-backed causal chains, explicit assumptions, and pre-registered verification.",
  applicationName: "Benmo",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "Benmo",
    title: "Benmo — Public causal research",
    description: "A public record of causal hypotheses, evidence, and verification.",
    images: [{ url: "/og.png", width: 1760, height: 907, alt: "Benmo public causal research" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Benmo — Public causal research",
    description: "A public record of causal hypotheses, evidence, and verification.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const organization = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Benmo",
    url: siteUrl,
    description: "A public causal research platform.",
  };
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <SiteHeader />
        <div id="main-content">{children}</div>
        <SiteFooter />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organization).replaceAll("<", "\\u003c") }}
        />
      </body>
    </html>
  );
}
