"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { CopyButton, JobStateBadge, PageHeader } from "@/components/common";
import { JobActions } from "@/components/job-actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useJob } from "@/lib/api/hooks";
import { dateTime } from "@/lib/format";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

export default function JobPage({ params }: PageProps<"/jobs/[id]">) {
  const { id } = use(params);
  const { data: job, isLoading, error } = useJob(Number(id));

  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !job) return <p className="text-sm text-destructive">{error?.message ?? "Not found"}</p>;

  return (
    <>
      <Button variant="ghost" size="sm" className="mb-2" render={<Link href="/jobs" />} nativeButton={false}>
        <ArrowLeft /> Jobs
      </Button>
      <PageHeader title={job.video.title || job.video.yt_video_id} description={`Job #${job.id}`}>
        <JobStateBadge state={job.state} />
        <JobActions job={job} />
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                Caption
                {job.caption && <CopyButton text={job.caption} />}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="rounded-lg bg-muted p-3 font-sans text-sm whitespace-pre-wrap">
                {job.caption ?? "Built when the upload starts."}
              </pre>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="grid gap-2 border-l pl-4">
                {job.events.map((e) => (
                  <li key={e.id} className="text-sm">
                    <span className="text-xs text-muted-foreground">{dateTime(e.ts)}</span>
                    <div className={e.level === "WARNING" ? "text-amber-700 dark:text-amber-300" : ""}>
                      {e.message}
                    </div>
                  </li>
                ))}
                {job.events.length === 0 && (
                  <li className="text-sm text-muted-foreground">No events yet</li>
                )}
              </ol>
            </CardContent>
          </Card>
        </div>
        <Card className="content-start">
          <CardContent className="grid gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={job.video.thumbnail_url} alt="" className="w-full rounded-lg" />
            <a
              href={job.video.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-sm hover:underline"
            >
              Open on YouTube <ExternalLink className="size-3.5" />
            </a>
            <div>
              <Row label="Source">{job.source_title ?? "—"}</Row>
              <Row label="Account">{job.target_name}</Row>
              <Row label="Download">
                {job.video.download_status}
                {job.video.skip_reason && ` (${job.video.skip_reason})`}
              </Row>
              <Row label="Attempts">{job.attempts}</Row>
              <Row label="Created">{dateTime(job.created_at)}</Row>
              <Row label="Uploaded">{dateTime(job.uploaded_at)}</Row>
              <Row label="Finished">{dateTime(job.finished_at)}</Row>
              {job.next_attempt_at && <Row label="Next attempt">{dateTime(job.next_attempt_at)}</Row>}
              <Row label="Publish ID">{job.publish_id ?? "—"}</Row>
              <Row label="TikTok log ID">{job.tiktok_log_id ?? "—"}</Row>
              {job.last_error && (
                <Row label="Last error">
                  <span className="text-destructive">{job.last_error}</span>
                </Row>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
