import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ProgressTracker } from "@/components/progress-tracker";
import { ApiError, getAnalysis } from "@/lib/api";

export const metadata: Metadata = {
  title: "Analysis progress",
  robots: { index: false, follow: false, noarchive: true },
};

export default async function ProgressPage({
  params,
}: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = await params;
  let analysis;
  try {
    analysis = await getAnalysis(ref);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  return <ProgressTracker initial={analysis} />;
}
