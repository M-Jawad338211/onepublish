import { NextResponse, type NextRequest } from "next/server";

/** Sends signed-out visitors to /login. The API still checks the cookie on every call. */
export function proxy(request: NextRequest) {
  if (request.cookies.has("op_session")) return NextResponse.next();
  const login = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api|login|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico)$).*)"],
};
