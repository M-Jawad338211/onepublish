"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useState } from "react";

import { CopyButton, Field, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { Settings } from "@/lib/api/client";
import { useSettings, useStatus, useUpdateSettings } from "@/lib/api/hooks";

function Check({ ok, label, hint }: { ok: boolean; label: string; hint?: string }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      {ok ? (
        <CheckCircle2 className="mt-0.5 size-4 text-emerald-600" />
      ) : (
        <XCircle className="mt-0.5 size-4 text-muted-foreground" />
      )}
      <div>
        {label}
        {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
      </div>
    </div>
  );
}

function DefaultsForm({ initial }: { initial: Settings }) {
  const save = useUpdateSettings();
  const [cap, setCap] = useState(String(initial.staging_cap_gb));
  const [poll, setPoll] = useState(String(initial.default_poll_interval_s / 60));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Defaults</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({
              staging_cap_gb: Number(cap),
              default_poll_interval_s: Math.round(Number(poll) * 60),
            });
          }}
        >
          <Field
            label="Staging cap (GB)"
            hint="Downloads pause at 80%. Files are deleted once every account has its draft."
          >
            <Input type="number" step="0.5" min="0.5" value={cap} onChange={(e) => setCap(e.target.value)} />
          </Field>
          <Field label="Poll interval for new sources (minutes)" hint="Minimum 2 minutes">
            <Input type="number" min="2" value={poll} onChange={(e) => setPoll(e.target.value)} />
          </Field>
          <Button type="submit" className="justify-self-start" disabled={save.isPending}>
            Save
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { data } = useSettings();
  const { data: status } = useStatus();

  if (!data) return <Skeleton className="h-96" />;

  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-4 lg:grid-cols-2">
        <DefaultsForm key={`${data.staging_cap_gb}-${data.default_poll_interval_s}`} initial={data} />
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
            <CardDescription>Set through Railway variables; shown here for checking.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Check ok={data.tiktok_client_configured} label="TikTok client key and secret" />
            <div className="grid gap-1 text-sm">
              <span>TikTok redirect URI (register this in the developer portal)</span>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs">
                  {data.tiktok_redirect_uri || "not set"}
                </code>
                {data.tiktok_redirect_uri && <CopyButton text={data.tiktok_redirect_uri} size="xs" />}
              </div>
            </div>
            <Check
              ok={data.cookies_configured}
              label="YouTube cookies"
              hint="Needed on Railway's datacenter IPs to avoid the bot check"
            />
            <Check ok={data.proxy_configured} label="Residential proxy for yt-dlp" hint="Optional fallback" />
            <Check ok label={`PO-token provider at ${data.pot_provider_url}`} />
            <Check
              ok={!!status?.worker_alive}
              label={`Worker ${status?.worker_alive ? "running" : "not reporting"}`}
              hint={status?.ytdlp_version ? `yt-dlp ${status.ytdlp_version}` : undefined}
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
