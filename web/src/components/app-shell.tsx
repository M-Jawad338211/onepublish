"use client";

import {
  Bell,
  Gauge,
  Link2,
  ListVideo,
  LogOut,
  Settings,
  Clapperboard,
  Send,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useResumeDownloads, useStatus, useUnreadCount } from "@/lib/api/hooks";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/jobs", label: "Jobs", icon: ListVideo },
  { href: "/sources", label: "Sources", icon: Clapperboard },
  { href: "/targets", label: "Targets", icon: Send },
  { href: "/mappings", label: "Mappings", icon: Link2 },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];

function WorkerDot() {
  const { data } = useStatus();
  const alive = data?.worker_alive;
  return (
    <span
      className="flex items-center gap-1.5 text-xs text-muted-foreground"
      title={alive ? "Worker is running" : "No worker heartbeat in the last 2 minutes"}
    >
      <span
        className={cn(
          "size-2 rounded-full",
          data === undefined ? "bg-muted-foreground/40" : alive ? "bg-emerald-500" : "bg-red-500",
        )}
      />
      Worker {data === undefined ? "…" : alive ? "running" : "down"}
    </span>
  );
}

function PausedBanner() {
  const { data } = useStatus();
  const resume = useResumeDownloads();
  if (!data?.downloads_paused_reason) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <div>
        <p className="font-medium">Downloads are paused: {data.downloads_paused_reason}</p>
        <p className="text-muted-foreground">
          YouTube rejected the cookies. Nothing is retried until you replace YTDLP_COOKIES_B64 (or
          set YTDLP_PROXY) on Railway, which resumes automatically, or resume here once it&apos;s
          fixed.
        </p>
      </div>
      <Button size="sm" variant="outline" disabled={resume.isPending} onClick={() => resume.mutate(undefined)}>
        Resume downloads
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: unread } = useUnreadCount();

  async function logout() {
    await api.POST("/api/auth/logout");
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b bg-muted/30 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-2 px-4 py-4">
          <Link href="/" className="font-semibold tracking-tight">
            OnePublish
          </Link>
          <WorkerDot />
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-background font-medium shadow-sm ring-1 ring-foreground/10"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {label}
                {href === "/alerts" && !!unread?.unread && (
                  <span className="ml-auto rounded-full bg-primary px-1.5 text-[11px] font-medium text-primary-foreground">
                    {unread.unread}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="hidden px-2 md:absolute md:bottom-3 md:block md:w-56">
          <Button variant="ghost" className="w-full justify-start" onClick={logout}>
            <LogOut /> Sign out
          </Button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <div className="mx-auto max-w-6xl">
          <PausedBanner />
          {children}
        </div>
        <div className="mt-10 md:hidden">
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut /> Sign out
          </Button>
        </div>
      </main>
    </div>
  );
}
