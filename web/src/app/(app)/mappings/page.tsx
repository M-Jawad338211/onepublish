"use client";

import { Settings2 } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState, Field, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Mapping, Source, Target } from "@/lib/api/client";
import {
  captionPreview,
  useCreateMapping,
  useMappings,
  useSources,
  useTargets,
  useUpdateMapping,
} from "@/lib/api/hooks";

const SAMPLE = {
  title: "Three-ingredient pasta in 60 seconds",
  description:
    "Full recipe on my channel! https://example.com @friend #shorts #pasta",
  tags: ["quick recipes", "pasta", "shorts"],
};

const splitTags = (s: string) =>
  s
    .split(/[\s,]+/)
    .map((t) => t.replace(/^#/, ""))
    .filter(Boolean);

function CaptionDialog({
  mapping,
  title,
  onClose,
}: {
  mapping: Mapping | null;
  title: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!mapping} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Caption for {title}</DialogTitle>
          <DialogDescription>
            Drafts can&apos;t carry a caption, so this text is kept on the job
            for you to paste.
          </DialogDescription>
        </DialogHeader>
        {mapping && (
          <CaptionForm key={mapping.id} mapping={mapping} onClose={onClose} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function CaptionForm({
  mapping,
  onClose,
}: {
  mapping: Mapping;
  onClose: () => void;
}) {
  const update = useUpdateMapping();
  const [form, setForm] = useState({
    include_title: mapping.include_title ?? true,
    include_description: mapping.include_description ?? true,
    include_tags: mapping.include_tags ?? true,
    caption_prefix: mapping.caption_prefix ?? "",
    caption_suffix: mapping.caption_suffix ?? "",
    extra_tags: (mapping.extra_tags ?? []).join(" "),
    strip_tags: (mapping.strip_tags ?? []).join(" "),
    max_len: mapping.max_len ? String(mapping.max_len) : "",
  });
  const [preview, setPreview] = useState("");

  const body = {
    include_title: form.include_title,
    include_description: form.include_description,
    include_tags: form.include_tags,
    caption_prefix: form.caption_prefix,
    caption_suffix: form.caption_suffix,
    extra_tags: splitTags(form.extra_tags),
    strip_tags: splitTags(form.strip_tags),
    max_len: form.max_len ? Number(form.max_len) : null,
  };
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    const t = setTimeout(() => {
      captionPreview({ ...JSON.parse(bodyKey), ...SAMPLE })
        .then((r) => setPreview(r.caption))
        .catch(() => setPreview(""));
    }, 250);
    return () => clearTimeout(t);
  }, [bodyKey]);

  const toggle = (
    key: "include_title" | "include_description" | "include_tags",
    label: string,
  ) => (
    <label className="flex items-center gap-2 text-sm">
      <Switch
        checked={form[key]}
        onCheckedChange={(v) => setForm({ ...form, [key]: v })}
      />
      {label}
    </label>
  );

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid content-start gap-3">
          <div className="flex flex-wrap gap-4">
            {toggle("include_title", "Title")}
            {toggle("include_description", "Description")}
            {toggle("include_tags", "Tags")}
          </div>
          <Field label="Prefix">
            <Input
              value={form.caption_prefix}
              onChange={(e) =>
                setForm({ ...form, caption_prefix: e.target.value })
              }
            />
          </Field>
          <Field label="Suffix">
            <Input
              value={form.caption_suffix}
              onChange={(e) =>
                setForm({ ...form, caption_suffix: e.target.value })
              }
            />
          </Field>
          <Field label="Extra hashtags" hint="Space or comma separated">
            <Input
              value={form.extra_tags}
              onChange={(e) => setForm({ ...form, extra_tags: e.target.value })}
            />
          </Field>
          <Field
            label="Remove hashtags"
            hint="YouTube-only tags such as shorts"
          >
            <Input
              value={form.strip_tags}
              onChange={(e) => setForm({ ...form, strip_tags: e.target.value })}
            />
          </Field>
          <Field
            label="Max length"
            hint="TikTok allows 2200; leave empty for that"
          >
            <Input
              type="number"
              min={50}
              max={2200}
              value={form.max_len}
              onChange={(e) => setForm({ ...form, max_len: e.target.value })}
            />
          </Field>
        </div>
        <div className="grid content-start gap-1.5 text-sm">
          <span className="font-medium">Preview with a sample Short</span>
          <pre className="min-h-40 rounded-lg bg-muted p-3 font-sans text-sm whitespace-pre-wrap">
            {preview || "…"}
          </pre>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={update.isPending}
          onClick={() =>
            update.mutate({ id: mapping.id, ...body }, { onSuccess: onClose })
          }
        >
          Save
        </Button>
      </DialogFooter>
    </>
  );
}

function Cell({
  source,
  target,
  mapping,
  onEdit,
}: {
  source: Source;
  target: Target;
  mapping?: Mapping;
  onEdit: (m: Mapping) => void;
}) {
  const create = useCreateMapping();
  const update = useUpdateMapping();
  const on = !!mapping?.enabled;
  return (
    <div className="flex items-center gap-1">
      <Switch
        checked={on}
        disabled={create.isPending || update.isPending}
        onCheckedChange={(checked) =>
          mapping
            ? update.mutate({ id: mapping.id, enabled: checked })
            : create.mutate({ source_id: source.id, target_id: target.id })
        }
      />
      {mapping && (
        <Button
          variant="ghost"
          size="icon-xs"
          title="Caption settings"
          onClick={() => onEdit(mapping)}
        >
          <Settings2 />
        </Button>
      )}
    </div>
  );
}

export default function MappingsPage() {
  const sources = useSources();
  const targets = useTargets();
  const mappings = useMappings();
  const [editing, setEditing] = useState<Mapping | null>(null);

  const loading = sources.isLoading || targets.isLoading || mappings.isLoading;
  const find = (s: number, t: number) =>
    mappings.data?.find((m) => m.source_id === s && m.target_id === t);
  const label = (m: Mapping | null) => {
    if (!m) return "";
    const s = sources.data?.find((x) => x.id === m.source_id)?.title;
    const t = targets.data?.find((x) => x.id === m.target_id)?.display_name;
    return `${s} → ${t}`;
  };

  return (
    <>
      <PageHeader
        title="Mappings"
        description="Pick which channels feed which TikTok accounts. Turning a mapping off doesn't back-fill Shorts posted while it was off."
      />
      {loading && <Skeleton className="h-40" />}
      {!loading && (!sources.data?.length || !targets.data?.length) && (
        <EmptyState title="Add a source and connect a TikTok account first" />
      )}
      {!!sources.data?.length && !!targets.data?.length && (
        <Card className="overflow-x-auto py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Channel ↓ / Account →</TableHead>
                {targets.data.map((t) => (
                  <TableHead key={t.id}>{t.display_name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.data.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.title}</TableCell>
                  {targets.data.map((t) => (
                    <TableCell key={t.id}>
                      <Cell
                        source={s}
                        target={t}
                        mapping={find(s.id, t.id)}
                        onEdit={setEditing}
                      />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      <CaptionDialog
        mapping={editing}
        title={label(editing)}
        onClose={() => setEditing(null)}
      />
    </>
  );
}
