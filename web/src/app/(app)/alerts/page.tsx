"use client";

import {
  AlertTriangle,
  CheckCheck,
  HardDrive,
  Inbox,
  KeyRound,
  PauseCircle,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "cn";

import { CopyButton, EmptyState, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Alert, Schemas } from "@/lib/api/client";
import { useAlerts, useMarkAllRead, useMarkRead } from "@/lib/api/hooks";
import { relativeTime } from "@/lib/format";

const ICONS: Record<Schemas["AlertKind"], React.ElementType> = {
  DRAFT_READY: Inbox,
  TOKEN_EXPIRING: KeyRound,
  TARGET_NEEDS_RECONNECT: KeyRound,
  DOWNLOAD_FAILING: AlertTriangle,
  BOT_CHECK: ShieldAlert,
  TARGET_PAUSED: PauseCircle,
  DISK_HIGH: HardDrive,
  JOB_FAILED: XCircle,
};

function AlertRow({ alert }: { alert: Alert }) {
  const markRead = useMarkRead();
  const Icon = ICONS[alert.kind];
  const unread = !alert.read_at;
  const caption = alert.kind === "DRAFT_READY" ? String(alert.payload.caption ?? "") : null;

  return (
    <div className={cn("flex gap-3 p-4", unread ? "" : "opacity-60")}>
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          alert.kind === "DRAFT_READY" ? "text-emerald-600" : "text-amber-600",
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm">{alert.message}</p>
        <p className="text-xs text-muted-foreground">
          {relativeTime(alert.created_at)}
          {alert.job_id && (
            <>
              {" · "}
              <Link href={`/jobs/${alert.job_id}`} className="underline">
                job #{alert.job_id}
              </Link>
            </>
          )}
        </p>
        {caption && (
          <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-muted p-2 font-sans text-xs whitespace-pre-wrap">
            {caption}
          </pre>
        )}
      </div>
      <div className="flex shrink-0 items-start gap-1">
        {caption && <CopyButton text={caption} label="Caption" size="xs" />}
        {unread && (
          <Button variant="ghost" size="xs" onClick={() => markRead.mutate(alert.id)}>
            Mark read
          </Button>
        )}
      </div>
    </div>
  );
}

export default function AlertsPage() {
  const [unreadOnly, setUnreadOnly] = useState(true);
  const { data, isLoading } = useAlerts(unreadOnly);
  const markAll = useMarkAllRead();

  return (
    <>
      <PageHeader title="Alerts" description="Drafts ready to post, and anything that needs you.">
        <Button variant="outline" size="sm" onClick={() => setUnreadOnly(!unreadOnly)}>
          {unreadOnly ? "Show all" : "Unread only"}
        </Button>
        <Button size="sm" disabled={markAll.isPending} onClick={() => markAll.mutate(undefined)}>
          <CheckCheck /> Mark all read
        </Button>
      </PageHeader>
      {isLoading && <Skeleton className="h-40" />}
      {data?.length === 0 && <EmptyState title={unreadOnly ? "All caught up" : "No alerts yet"} />}
      {!!data?.length && (
        <Card className="divide-y py-0">
          {data.map((a) => (
            <AlertRow key={a.id} alert={a} />
          ))}
        </Card>
      )}
    </>
  );
}
