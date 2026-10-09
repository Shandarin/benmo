export function formatDate(value: string | null): string {
  if (!value) return "Date not specified";
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export function formatPercent(value: string | number | null): string {
  if (value === null) return "Not available";
  const number = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "Not available";
}

export function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
