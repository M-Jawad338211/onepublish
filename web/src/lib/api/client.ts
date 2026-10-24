import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Source = Schemas["SourceOut"];
export type Target = Schemas["TargetOut"];
export type Mapping = Schemas["MappingOut"];
export type Job = Schemas["JobOut"];
export type JobDetail = Schemas["JobDetail"];
export type JobState = Schemas["JobState"];
export type Alert = Schemas["AlertOut"];
export type Settings = Schemas["SettingsOut"];
export type Status = Schemas["StatusOut"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const redirectOn401: Middleware = {
  onResponse({ response, request }) {
    const isAuthCall = new URL(request.url).pathname.startsWith("/api/auth/");
    if (response.status === 401 && !isAuthCall && typeof window !== "undefined") {
      const next = window.location.pathname + window.location.search;
      // Outside React, so a hard navigation is the only option here.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
  },
};

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(redirectOn401);

function errorMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${d.loc?.slice(1).join(".")}: ${d.msg}`)
      .join("; ");
  }
  return "Request failed";
}

/** Throws ApiError on non-2xx so React Query sees a rejected promise. */
export async function unwrap<T>(
  p: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await p;
  if (!response.ok) throw new ApiError(response.status, errorMessage(error));
  return data as T;
}
