"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap, type JobState, type Schemas } from "./client";

const POLL_MS = 15_000;

export const keys = {
  sources: ["sources"] as const,
  targets: ["targets"] as const,
  mappings: ["mappings"] as const,
  jobs: (f: JobFilters) => ["jobs", f] as const,
  job: (id: number) => ["job", id] as const,
  alerts: (unread: boolean) => ["alerts", unread] as const,
  unread: ["alerts", "unread-count"] as const,
  settings: ["settings"] as const,
  status: ["status"] as const,
};

/** Wraps a mutation with error toasts and cache invalidation. */
function useAction<TVars, TData>(
  fn: (vars: TVars) => Promise<TData>,
  invalidate: QueryKey[],
  success?: string | ((data: TData) => string),
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      invalidate.forEach((queryKey) => qc.invalidateQueries({ queryKey }));
      if (success) toast.success(typeof success === "function" ? success(data) : success);
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

// --- sources -------------------------------------------------------------------

export const useSources = () =>
  useQuery({ queryKey: keys.sources, queryFn: () => unwrap(api.GET("/api/sources")) });

export const useCreateSource = () =>
  useAction(
    (body: Schemas["SourceCreate"]) => unwrap(api.POST("/api/sources", { body })),
    [keys.sources],
    (s) => `Added ${s.title}`,
  );

export const useUpdateSource = () =>
  useAction(
    ({ id, ...body }: Schemas["SourceUpdate"] & { id: number }) =>
      unwrap(api.PATCH("/api/sources/{source_id}", { params: { path: { source_id: id } }, body })),
    [keys.sources],
  );

export const useDeleteSource = () =>
  useAction(
    (id: number) =>
      unwrap(api.DELETE("/api/sources/{source_id}", { params: { path: { source_id: id } } })),
    [keys.sources, keys.mappings],
    "Source removed",
  );

export const useCheckNow = () =>
  useAction(
    (id: number) =>
      unwrap(
        api.POST("/api/sources/{source_id}/check-now", { params: { path: { source_id: id } } }),
      ),
    [keys.sources],
    "Checking within 30 seconds",
  );

// --- targets -------------------------------------------------------------------

export const useTargets = () =>
  useQuery({
    queryKey: keys.targets,
    queryFn: () => unwrap(api.GET("/api/targets")),
    refetchInterval: POLL_MS * 2,
  });

export const useUpdateTarget = () =>
  useAction(
    ({ id, ...body }: Schemas["TargetUpdate"] & { id: number }) =>
      unwrap(api.PATCH("/api/targets/{target_id}", { params: { path: { target_id: id } }, body })),
    [keys.targets],
  );

export const useDisconnectTarget = () =>
  useAction(
    (id: number) =>
      unwrap(api.DELETE("/api/targets/{target_id}", { params: { path: { target_id: id } } })),
    [keys.targets, keys.mappings],
    "Account disconnected",
  );

// --- mappings ------------------------------------------------------------------

export const useMappings = () =>
  useQuery({ queryKey: keys.mappings, queryFn: () => unwrap(api.GET("/api/mappings")) });

export const useCreateMapping = () =>
  useAction(
    (body: Schemas["MappingCreate"]) => unwrap(api.POST("/api/mappings", { body })),
    [keys.mappings],
  );

export const useUpdateMapping = () =>
  useAction(
    ({ id, ...body }: Schemas["MappingUpdate"] & { id: number }) =>
      unwrap(
        api.PATCH("/api/mappings/{mapping_id}", { params: { path: { mapping_id: id } }, body }),
      ),
    [keys.mappings],
  );

export const useDeleteMapping = () =>
  useAction(
    (id: number) =>
      unwrap(api.DELETE("/api/mappings/{mapping_id}", { params: { path: { mapping_id: id } } })),
    [keys.mappings],
  );

export const captionPreview = (body: Schemas["CaptionPreviewIn"]) =>
  unwrap(api.POST("/api/mappings/caption-preview", { body }));

// --- jobs ----------------------------------------------------------------------

export type JobFilters = {
  state?: JobState[];
  source_id?: number;
  target_id?: number;
};

export const useJobs = (filters: JobFilters) =>
  useInfiniteQuery({
    queryKey: keys.jobs(filters),
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/jobs", {
          params: { query: { ...filters, cursor: pageParam, limit: 50 } },
          querySerializer: { array: { style: "form", explode: true } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: POLL_MS,
  });

export const useJob = (id: number) =>
  useQuery({
    queryKey: keys.job(id),
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
    refetchInterval: POLL_MS,
  });

const jobKeys: QueryKey[] = [["jobs"], ["job"], keys.status];

export const useRetryJob = () =>
  useAction(
    (id: number) =>
      unwrap(api.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: id } } })),
    jobKeys,
    "Queued again",
  );

export const useSkipJob = () =>
  useAction(
    (id: number) =>
      unwrap(api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } })),
    jobKeys,
    "Skipped",
  );

export const useResendJob = () =>
  useAction(
    ({ id, target_id }: { id: number; target_id: number }) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/resend", {
          params: { path: { job_id: id } },
          body: { target_id },
        }),
      ),
    jobKeys,
    (j) => `Queued for ${j.target_name}`,
  );

// --- alerts --------------------------------------------------------------------

export const useAlerts = (unread = false) =>
  useQuery({
    queryKey: keys.alerts(unread),
    queryFn: () => unwrap(api.GET("/api/alerts", { params: { query: { unread, limit: 200 } } })),
    refetchInterval: POLL_MS,
  });

export const useUnreadCount = () =>
  useQuery({
    queryKey: keys.unread,
    queryFn: () => unwrap(api.GET("/api/alerts/unread-count")),
    refetchInterval: POLL_MS,
  });

export const useMarkRead = () =>
  useAction(
    (id: number) =>
      unwrap(api.POST("/api/alerts/{alert_id}/read", { params: { path: { alert_id: id } } })),
    [["alerts"]],
  );

export const useMarkAllRead = () =>
  useAction(() => unwrap(api.POST("/api/alerts/read-all")), [["alerts"]], "All caught up");

// --- settings / status -------------------------------------------------------------

export const useSettings = () =>
  useQuery({ queryKey: keys.settings, queryFn: () => unwrap(api.GET("/api/settings")) });

export const useUpdateSettings = () =>
  useAction(
    (body: Schemas["SettingsUpdate"]) => unwrap(api.PATCH("/api/settings", { body })),
    [keys.settings, keys.status],
    "Settings saved",
  );

export const useStatus = () =>
  useQuery({
    queryKey: keys.status,
    queryFn: () => unwrap(api.GET("/api/status")),
    refetchInterval: POLL_MS,
  });
