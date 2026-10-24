"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "cn";

import {
  ALL_JOB_STATES,
  CopyButton,
  EmptyState,
  JobStateBadge,
  NativeSelect,
  PageHeader,
  jobStateLabel,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { JobActions } from "@/components/job-actions";
import type { JobState } from "@/lib/api/client";
import { type JobFilters, useJobs, useSources, useTargets } from "@/lib/api/hooks";
import { relativeTime } from "@/lib/format";

const RETRYABLE: JobState[] = ["FAILED", "FAILED_EXPIRED", "SKIPPED"];

function StateChips({
  value,
  onChange,
}: {
  value: JobState[];
  onChange: (v: JobState[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {ALL_JOB_STATES.map((s) => {
        const on = value.includes(s);
        return (
          <button
            key={s}
            type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== s) : [...value, s])}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
              on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
            )}
          >
            {jobStateLabel(s)}
          </button>
        );
      })}
    </div>
  );
}

export default function JobsPage() {
  const router = useRouter();
  const [filters, setFilters] = useState<JobFilters>({});
  const jobs = useJobs(filters);
  const { data: sources } = useSources();
  const { data: targets } = useTargets();
  const items = jobs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <PageHeader title="Jobs" description="One row per Short per TikTok account.">
        <NativeSelect
          value={filters.source_id ?? ""}
          onChange={(e) =>
            setFilters({ ...filters, source_id: e.target.value ? Number(e.target.value) : undefined })
          }
        >
          <option value="">All sources</option>
          {sources?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          value={filters.target_id ?? ""}
          onChange={(e) =>
            setFilters({ ...filters, target_id: e.target.value ? Number(e.target.value) : undefined })
          }
        >
          <option value="">All accounts</option>
          {targets?.map((t) => (
            <option key={t.id} value={t.id}>
              {t.display_name}
            </option>
          ))}
        </NativeSelect>
      </PageHeader>
      <div className="mb-4">
        <StateChips
          value={filters.state ?? []}
          onChange={(state) => setFilters({ ...filters, state: state.length ? state : undefined })}
        />
      </div>

      {jobs.isLoading && <Skeleton className="h-64" />}
      {!jobs.isLoading && items.length === 0 && (
        <EmptyState title="No jobs match">New Shorts appear here as soon as they are detected.</EmptyState>
      )}
      {items.length > 0 && (
        <Card className="overflow-x-auto py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Short</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead>Caption</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((job) => (
                <TableRow
                  key={job.id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/jobs/${job.id}`)}
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={job.video.thumbnail_url}
                        alt=""
                        className="h-12 w-9 rounded object-cover"
                        loading="lazy"
                      />
                      <div className="min-w-0 max-w-72">
                        <Link
                          href={`/jobs/${job.id}`}
                          className="block truncate font-medium hover:underline"
                        >
                          {job.video.title || job.video.yt_video_id}
                        </Link>
                        <div className="truncate text-xs text-muted-foreground">
                          {job.source_title ?? "deleted source"}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{job.target_name}</TableCell>
                  <TableCell>
                    <JobStateBadge state={job.state} />
                    {job.state === "UPLOADING" && job.total_chunks && (
                      <div className="text-xs text-muted-foreground">
                        chunk {job.chunks_done}/{job.total_chunks}
                      </div>
                    )}
                    {job.last_error && RETRYABLE.includes(job.state) && (
                      <div className="max-w-48 truncate text-xs text-destructive" title={job.last_error}>
                        {job.last_error}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    {relativeTime(job.finished_at ?? job.uploaded_at ?? job.created_at)}
                  </TableCell>
                  <TableCell>
                    {job.caption ? <CopyButton text={job.caption} size="xs" /> : "—"}
                  </TableCell>
                  <TableCell>
                    <JobActions job={job} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {jobs.hasNextPage && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="outline"
            disabled={jobs.isFetchingNextPage}
            onClick={() => jobs.fetchNextPage()}
          >
            Load more
          </Button>
        </div>
      )}
    </>
  );
}
