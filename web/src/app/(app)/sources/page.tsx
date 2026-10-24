"use client";

import { Pause, Play, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  ConfirmDialog,
  EmptyState,
  Field,
  NativeSelect,
  PageHeader,
  StatusBadge,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Source } from "@/lib/api/client";
import {
  useCheckNow,
  useCreateSource,
  useDeleteSource,
  useSources,
  useUpdateSource,
} from "@/lib/api/hooks";
import { interval, relativeTime } from "@/lib/format";

const INTERVALS = [120, 300, 600, 900, 1800, 3600];

function AddSource() {
  const create = useCreateSource();
  const [url, setUrl] = useState("");
  const [startFrom, setStartFrom] = useState("");

  return (
    <Card>
      <CardContent>
        <form
          className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { url, start_from: startFrom ? new Date(startFrom).toISOString() : null },
              { onSuccess: () => (setUrl(""), setStartFrom("")) },
            );
          }}
        >
          <Field label="YouTube channel URL" hint="/@handle, /channel/UC…, /c/name or /user/name">
            <Input
              placeholder="https://www.youtube.com/@yourchannel"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </Field>
          <Field label="Start from (optional)" hint="Default: only Shorts posted after adding">
            <Input
              type="datetime-local"
              value={startFrom}
              onChange={(e) => setStartFrom(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={create.isPending || !url}>
            {create.isPending ? "Resolving…" : "Add source"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function SourceRow({ source, onDelete }: { source: Source; onDelete: () => void }) {
  const update = useUpdateSource();
  const checkNow = useCheckNow();
  const paused = source.status === "PAUSED";
  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-3">
          {source.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={source.thumbnail_url} alt="" className="size-8 rounded-full" />
          ) : (
            <div className="size-8 rounded-full bg-muted" />
          )}
          <div className="min-w-0">
            <a href={source.url} target="_blank" rel="noreferrer" className="font-medium hover:underline">
              {source.title}
            </a>
            <div className="text-xs text-muted-foreground">{source.handle ?? source.channel_id}</div>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <StatusBadge status={source.status} />
      </TableCell>
      <TableCell>
        <NativeSelect
          value={source.poll_interval_s}
          onChange={(e) => update.mutate({ id: source.id, poll_interval_s: Number(e.target.value) })}
        >
          {[...new Set([...INTERVALS, source.poll_interval_s])].sort((a, b) => a - b).map((s) => (
            <option key={s} value={s}>
              every {interval(s)}
            </option>
          ))}
        </NativeSelect>
      </TableCell>
      <TableCell className="text-sm">
        {relativeTime(source.last_polled_at)}
        {source.last_error && (
          <div className="max-w-56 truncate text-xs text-destructive" title={source.last_error}>
            {source.last_error}
          </div>
        )}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            title="Check now"
            disabled={paused || checkNow.isPending}
            onClick={() => checkNow.mutate(source.id)}
          >
            <RefreshCw />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            title={paused ? "Resume" : "Pause"}
            onClick={() => update.mutate({ id: source.id, status: paused ? "ACTIVE" : "PAUSED" })}
          >
            {paused ? <Play /> : <Pause />}
          </Button>
          <Button variant="ghost" size="icon-sm" title="Delete" onClick={onDelete}>
            <Trash2 />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function SourcesPage() {
  const { data, isLoading } = useSources();
  const del = useDeleteSource();
  const [deleting, setDeleting] = useState<Source | null>(null);

  return (
    <>
      <PageHeader
        title="Sources"
        description="YouTube channels to watch. Only Shorts are picked up, through each channel's Shorts feed."
      />
      <div className="grid gap-4">
        <AddSource />
        {isLoading && <Skeleton className="h-32" />}
        {data?.length === 0 && (
          <EmptyState title="No sources yet">Add a channel above to start watching it.</EmptyState>
        )}
        {!!data?.length && (
          <Card className="py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Poll</TableHead>
                  <TableHead>Last checked</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((s) => (
                  <SourceRow key={s.id} source={s} onDelete={() => setDeleting(s)} />
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.title}?`}
        description="Its mappings are removed. Past jobs stay in the history."
        confirmLabel="Delete source"
        pending={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
      />
    </>
  );
}
