import { useState } from "react";
import { X } from "lucide-react";

import { adminJson } from "@/lib/workshop";

/**
 * Kevin's own groupings for an idea (2026-11-05): free-form tags the Ideas page can group by. Each change
 * saves the whole list; the server trims and dedupes it, and the chips show what it kept.
 */
export function TagEditor({ ideaId, initial }: { ideaId: number; initial: string[] }) {
  const [tags, setTags] = useState<string[]>(initial);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const save = async (next: string[]) => {
    setBusy(true);
    setFailed(false);
    try {
      const r = await adminJson<{ tags: string[] }>(`/api/workshop/ideas/${ideaId}/tags`,
        { method: "PUT", body: JSON.stringify({ tags: next }) });
      setTags(r.tags);
      setDraft("");
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-slate-400">Tags</span>
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-800/70 px-2 py-0.5 text-xs text-slate-200">
          {t}
          <button type="button" disabled={busy} onClick={() => void save(tags.filter((x) => x !== t))}
                  aria-label={`Remove tag ${t}`}
                  className="rounded-full text-slate-400 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 disabled:opacity-50">
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        aria-label="Add a tag"
        value={draft}
        disabled={busy}
        maxLength={24}
        placeholder={tags.length ? "Add" : "Add a tag, then Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draft.trim()) {
            e.preventDefault();
            void save([...tags, draft]);
          }
        }}
        className="w-36 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none"
      />
      {failed && <span role="alert" className="text-xs text-rose-300">Couldn't save the tags. Try again.</span>}
    </div>
  );
}
