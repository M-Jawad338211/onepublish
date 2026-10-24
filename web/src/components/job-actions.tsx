"use client";

import { MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Job, JobState } from "@/lib/api/client";
import { useResendJob, useRetryJob, useSkipJob, useTargets } from "@/lib/api/hooks";

const RETRYABLE: JobState[] = ["QUEUED", "FAILED", "FAILED_EXPIRED", "SKIPPED"];
const SKIPPABLE: JobState[] = ["QUEUED"];

export function JobActions({ job }: { job: Job }) {
  const retry = useRetryJob();
  const skip = useSkipJob();
  const resend = useResendJob();
  const { data: targets } = useTargets();
  const others = targets?.filter((t) => t.id !== job.target_id && t.status !== "DISCONNECTED");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon-sm" onClick={(e) => e.stopPropagation()} />}
      >
        <MoreHorizontal />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem
          disabled={!RETRYABLE.includes(job.state)}
          onClick={() => retry.mutate(job.id)}
        >
          {job.state === "QUEUED" ? "Retry now" : "Retry"}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!SKIPPABLE.includes(job.state)}
          onClick={() => skip.mutate(job.id)}
        >
          Skip
        </DropdownMenuItem>
        {!!others?.length && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Send to another account</DropdownMenuLabel>
            {others.map((t) => (
              <DropdownMenuItem
                key={t.id}
                onClick={() => resend.mutate({ id: job.id, target_id: t.id })}
              >
                {t.display_name}
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
