import type { NextRequest } from "next/server";

/**
 * Forwards /api/* to the FastAPI service over Railway's private network, so the browser
 * only ever talks to this origin (one cookie, no CORS). Resolved per request, so
 * API_INTERNAL_URL is a runtime variable, not baked in at build time.
 */
const API = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const HOP_BY_HOP = [
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
];

async function forward(req: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`, API);

  const headers = new Headers(req.headers);
  HOP_BY_HOP.forEach((h) => headers.delete(h));
  headers.set("x-forwarded-host", req.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", req.nextUrl.protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      redirect: "manual", // the OAuth flow's 302s must reach the browser untouched
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "API is unreachable" }, { status: 502 });
  }

  const out = new Headers(upstream.headers);
  // fetch already decoded the body; the original length/encoding no longer apply.
  ["content-encoding", "content-length", "transfer-encoding", "connection"].forEach((h) =>
    out.delete(h),
  );
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export {
  forward as GET,
  forward as POST,
  forward as PATCH,
  forward as PUT,
  forward as DELETE,
};
