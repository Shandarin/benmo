export function GET() {
  return Response.json(
    { status: "ok", service: "benmo-frontend" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
