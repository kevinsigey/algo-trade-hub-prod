import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, X } from "lucide-react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The open view a panel or dashboard card opens into: a modal with focus moved
 * to Close, Tab kept inside, Esc (anywhere on the page) closing it, and focus
 * handed back to whatever opened it. Full-screen on a phone, a large sheet
 * from `sm` up.
 */
export function FullView({ title, onClose, children, actions }: {
  title: string; onClose: () => void; children: ReactNode; actions?: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/60 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title}
           onClick={(e) => e.stopPropagation()}
           onKeyDown={(e) => {
             if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
             if (e.key !== "Tab") return;
             // Keep Tab inside the open view: wrap from the last control to the first, and back.
             const focusable = [...e.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)];
             if (!focusable.length) return;
             const first = focusable[0], last = focusable[focusable.length - 1];
             if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
             else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
           }}
           className="h-full w-full overflow-y-auto border-slate-700 bg-slate-900 p-4 sm:h-auto sm:max-h-[90vh] sm:max-w-6xl sm:rounded-2xl sm:border sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <div className="flex items-center gap-2">
            {actions}
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close"
                    className="rounded-md border border-slate-700 p-1.5 text-slate-300 hover:border-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}

/**
 * A dashboard panel that shows a summary and opens the whole thing on demand (Kevin, 2026-11-06: every
 * box a summary that can be opened up, like Composition, so a page fits on one screen). `full` is what the
 * open view shows; leave it out and the panel has no open control. Panels sit flush in a tight grid.
 */
export function Panel({ title, meta, full, fullTitle, children, className = "" }: {
  title: string; meta?: ReactNode; full?: ReactNode; fullTitle?: string; children: ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label={title} className={`flex min-w-0 flex-col rounded-lg border border-slate-800 bg-slate-900/60 p-3 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="truncate text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
        <div className="flex shrink-0 items-center gap-2">
          {meta}
          {full && (
            <button type="button" onClick={() => setOpen(true)} aria-label={`Open ${title} in full`} title="Open in full"
                    className="rounded-md border border-slate-700 p-1 text-slate-300 hover:border-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
              <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      <div className="mt-2 min-h-0 flex-1">{children}</div>
      {open && <FullView title={fullTitle ?? title} onClose={() => setOpen(false)}>{full}</FullView>}
    </section>
  );
}
