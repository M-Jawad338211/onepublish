"use client";

import { Pause, Play, Plus, Unplug } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, EmptyState, PageHeader, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Target } from "@/lib/api/client";
import { useDisconnectTarget, useTargets, useUpdateTarget } from "@/lib/api/hooks";
import { dateTime, relativeTime } from "@/lib/format";

/** Shows the result of the TikTok OAuth round trip, then cleans the URL. */
function ConnectResult() {
  const params = useSearchParams();
  const router = useRouter();
  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) toast.success(`Connected ${connected}`);
    if (error) toast.error(error);
    if (connected || error) router.replace("/targets");
  }, [params, router]);
  return null;
}

function TargetCard({ target, onDisconnect }: { target: Target; onDisconnect: () => void }) {
  const update = useUpdateTarget();
  const autoPaused = target.paused_until && new Date(target.paused_until) > new Date();
  const paused = target.status === "PAUSED";
  const used = target.quota_used ?? 0;
  const cap = target.quota_cap ?? 5;
  const pct = (used / cap) * 100;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          {target.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={target.avatar_url} alt="" className="size-10 rounded-full" />
          ) : (
            <div className="size-10 rounded-full bg-muted" />
          )}
          <div className="min-w-0">
            <CardTitle className="truncate">{target.display_name}</CardTitle>
            <StatusBadge status={target.status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <div>
          <div className="flex justify-between">
            <span>Uploads in the last 24 h</span>
            <span className="tabular-nums">
              {used}/{cap}
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          {target.next_slot_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              Next slot {relativeTime(target.next_slot_at)}
            </p>
          )}
        </div>
        {autoPaused && (
          <div className="rounded-lg bg-amber-500/10 p-2 text-xs">
            Paused by TikTok ({target.pause_reason}) until {dateTime(target.paused_until)}.
            <Button
              variant="link"
              size="xs"
              className="px-1"
              onClick={() => update.mutate({ id: target.id, clear_pause: true })}
            >
              Resume now
            </Button>
          </div>
        )}
        {target.status === "NEEDS_RECONNECT" && (
          <div className="rounded-lg bg-destructive/10 p-2 text-xs text-destructive">
            TikTok access was lost ({target.pause_reason}). Use “Connect TikTok” with this account
            again.
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          Login valid until {dateTime(target.refresh_expires_at)}
        </div>
      </CardContent>
      <CardFooter className="gap-2">
        {(target.status === "ACTIVE" || paused) && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => update.mutate({ id: target.id, status: paused ? "ACTIVE" : "PAUSED" })}
          >
            {paused ? <Play /> : <Pause />}
            {paused ? "Resume" : "Pause"}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onDisconnect}>
          <Unplug /> Disconnect
        </Button>
      </CardFooter>
    </Card>
  );
}

export default function TargetsPage() {
  const { data, isLoading } = useTargets();
  const disconnect = useDisconnectTarget();
  const [removing, setRemoving] = useState<Target | null>(null);

  return (
    <>
      <Suspense>
        <ConnectResult />
      </Suspense>
      <PageHeader
        title="Targets"
        description="TikTok accounts that receive drafts. Each account takes at most 5 uploads in any 24 h."
      >
        {/* A full page navigation: the API answers with a redirect to TikTok's consent page. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <Button render={<a href="/api/tiktok/connect" />} nativeButton={false}>
          <Plus /> Connect TikTok
        </Button>
      </PageHeader>
      {isLoading && <Skeleton className="h-40" />}
      {data?.length === 0 && (
        <EmptyState title="No TikTok accounts connected">
          In sandbox mode, only accounts added as target users in the TikTok developer portal can
          connect.
        </EmptyState>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((t) => (
          <TargetCard key={t.id} target={t} onDisconnect={() => setRemoving(t)} />
        ))}
      </div>
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Disconnect ${removing?.display_name}?`}
        description="The app's access is revoked at TikTok and its mappings are removed. Job history stays."
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        onConfirm={() =>
          removing && disconnect.mutate(removing.id, { onSuccess: () => setRemoving(null) })
        }
      />
    </>
  );
}
