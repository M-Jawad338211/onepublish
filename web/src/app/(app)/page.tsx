"use client";

import Link from "next/link";

import { CopyButton, JobStateBadge, PageHeader, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { JobState } from "@/lib/api/client";
import { useAlerts, useStatus, useTargets } from "@/lib/api/hooks";
import { bytes, relativeTime } from "@/lib/format";

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function StatusCard() {
  const { data: s } = useStatus();
  if (!s) return <Skeleton className="h-36" />;
  const pct = s.staging_cap_bytes ? Math.round((s.staging_bytes / s.staging_cap_bytes) * 100) : 0;
  const backoff = s.youtube_backoff_until && new Date(s.youtube_backoff_until) > new Date();
  return (
    <Card>
      <CardHeader>
        <CardTitle>System</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Worker"
          value={s.worker_alive ? "Running" : "Down"}
          hint={`heartbeat ${relativeTime(s.worker_heartbeat_at)}`}
        />
        <Stat label="Queued uploads" value={s.queued_jobs} />
        <Stat
          label="Staging"
          value={`${pct}%`}
          hint={`${bytes(s.staging_bytes)} of ${bytes(s.staging_cap_bytes)}`}
        />
        <Stat
          label="yt-dlp"
          value={s.ytdlp_version ?? "—"}
          hint={backoff ? `YouTube backoff until ${relativeTime(s.youtube_backoff_until)}` : undefined}
        />
        <div className="col-span-full flex flex-wrap gap-2">
          {Object.entries(s.jobs_last_24h).map(([state, n]) => (
            <span key={state} className="flex items-center gap-1 text-sm">
              <JobStateBadge state={state as JobState} />
              <span className="tabular-nums">{n}</span>
            </span>
          ))}
          {Object.keys(s.jobs_last_24h).length === 0 && (
            <span className="text-sm text-muted-foreground">No jobs in the last 24 h</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function TargetsCard() {
  const { data } = useTargets();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Draft slots per account</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {!data && <Skeleton className="h-16" />}
        {data?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No TikTok accounts yet. <Link href="/targets" className="underline">Connect one</Link>.
          </p>
        )}
        {data?.map((t) => (
          <div key={t.id} className="flex items-center justify-between gap-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-medium">{t.display_name}</span>
              <StatusBadge status={t.status} />
            </div>
            <div className="text-right tabular-nums">
              {t.quota_used ?? 0}/{t.quota_cap ?? 5} in 24 h
              {t.next_slot_at && (
                <div className="text-xs text-muted-foreground">
                  next slot {relativeTime(t.next_slot_at)}
                </div>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function DraftsCard() {
  const { data } = useAlerts(true);
  const drafts = data?.filter((a) => a.kind === "DRAFT_READY") ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Drafts waiting in TikTok</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {!data && <Skeleton className="h-16" />}
        {data && drafts.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing waiting. New drafts show up here.</p>
        )}
        {drafts.slice(0, 5).map((a) => (
          <div key={a.id} className="flex items-start justify-between gap-3 text-sm">
            <div className="min-w-0">
              <div className="truncate font-medium">{String(a.payload.video_title ?? "")}</div>
              <div className="text-xs text-muted-foreground">
                {String(a.payload.target ?? "")} · {relativeTime(a.created_at)}
              </div>
            </div>
            <CopyButton text={String(a.payload.caption ?? "")} label="Caption" size="xs" />
          </div>
        ))}
        {drafts.length > 5 && (
          <Button variant="link" className="justify-self-start px-0" render={<Link href="/alerts" />} nativeButton={false}>
            See all {drafts.length}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function OverviewPage() {
  return (
    <>
      <PageHeader title="Overview" description="New Shorts become TikTok inbox drafts." />
      <div className="grid gap-4">
        <StatusCard />
        <div className="grid gap-4 lg:grid-cols-2">
          <DraftsCard />
          <TargetsCard />
        </div>
      </div>
    </>
  );
}
