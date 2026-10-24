"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { cn } from "cn";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { JobState, Schemas } from "@/lib/api/client";

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function CopyButton({
  text,
  label = "Copy",
  size = "sm",
}: {
  text: string;
  label?: string;
  size?: "sm" | "xs" | "default";
}) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="outline"
      size={size}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          toast.success("Copied");
          setTimeout(() => setDone(false), 1500);
        } catch {
          toast.error("Clipboard is blocked; select the text and copy it");
        }
      }}
    >
      {done ? <Check /> : <Copy />}
      {label}
    </Button>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button variant="destructive" disabled={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const JOB_STATE_STYLE: Record<JobState, string> = {
  QUEUED: "bg-muted text-muted-foreground",
  INIT: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  UPLOADING: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  PROCESSING: "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300",
  SEND_TO_USER_INBOX: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  PUBLISH_COMPLETE: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  FAILED: "bg-destructive/15 text-destructive",
  FAILED_EXPIRED: "bg-destructive/15 text-destructive",
  SKIPPED: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

const JOB_STATE_LABEL: Partial<Record<JobState, string>> = {
  SEND_TO_USER_INBOX: "In TikTok inbox",
  PUBLISH_COMPLETE: "Published",
  FAILED_EXPIRED: "Expired",
};

export const ALL_JOB_STATES = Object.keys(JOB_STATE_STYLE) as JobState[];

export function jobStateLabel(state: JobState) {
  return JOB_STATE_LABEL[state] ?? state.charAt(0) + state.slice(1).toLowerCase();
}

export function JobStateBadge({ state }: { state: JobState }) {
  return (
    <Badge variant="outline" className={cn("border-transparent", JOB_STATE_STYLE[state])}>
      {jobStateLabel(state)}
    </Badge>
  );
}

const STATUS_STYLE: Record<string, string> = {
  ACTIVE: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  PAUSED: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  NEEDS_RECONNECT: "bg-destructive/15 text-destructive",
  DISCONNECTED: "bg-muted text-muted-foreground",
};

export function StatusBadge({
  status,
}: {
  status: Schemas["SourceStatus"] | Schemas["TargetStatus"];
}) {
  const label = status === "NEEDS_RECONNECT" ? "Reconnect needed" : status.toLowerCase();
  return (
    <Badge variant="outline" className={cn("border-transparent capitalize", STATUS_STYLE[status])}>
      {label}
    </Badge>
  );
}

export function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        className,
      )}
      {...props}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}
