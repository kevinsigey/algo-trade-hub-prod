import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import KalshiDemoBook from "@/pages/KalshiDemoBook";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  fmtPct,
  tone,
  type BookHeadline,
  type BooksPayload,
  type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { money, REFRESH_MS } from "@/pages/portfolio/shared";
import { PortfolioHeader, WarningsStrip } from "@/pages/portfolio/Header";
import BookTab from "@/pages/portfolio/BookTab";
import PerformanceTab from "@/pages/portfolio/PerformanceTab";
import TradeTab from "@/pages/portfolio/TradeTab";

/** The Portfolio page (2026-11-12 redesign): a fixed header, a warnings
 * strip, and three tabs -- Book (the default), Performance and Trade --
 * with the tab in the URL so it can be linked. The Kalshi demo book sits
 * beside the two Alpaca books in the switcher. Everything on the page
 * refreshes on a 30-second cycle while the tab is visible. */

function BookTabs({ book }: { book: string }) {
  const { data } = useApi<BooksPayload>("/api/portfolio/books");
  const books: BookHeadline[] = Array.isArray(data?.books) ? data.books : [];
  const shown = books.length ? books : [{ book: "main", label: "Main book" }, { book: "big", label: "$1M book" }] as BookHeadline[];
  return (
    <nav aria-label="Paper books" className="flex flex-wrap gap-2">
      {shown.map((b) => {
        const active = b.book === book;
        return (
          <Link key={b.book} to={`/portfolio?book=${b.book}`} aria-current={active ? "page" : undefined}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${active ? "border-emerald-500/50 bg-emerald-500/10" : "border-slate-700 hover:bg-slate-800/60"}`}>
            <span className={active ? "font-semibold text-white" : "text-slate-200"}>{b.label}</span>
            {b.state === "not_connected" ? (
              <span className="ml-2 text-xs text-slate-400">not connected</span>
            ) : b.equity != null && (
              <span className="ml-2 tabular-nums text-slate-300">
                {money(b.equity)} <span className={tone(b.return_pct)}>{fmtPct(b.return_pct)}</span>
              </span>
            )}
          </Link>
        );
      })}
      <Link to="/portfolio?book=kalshi" aria-current={book === "kalshi" ? "page" : undefined}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${book === "kalshi" ? "border-emerald-500/50 bg-emerald-500/10" : "border-slate-700 hover:bg-slate-800/60"}`}>
        <span className={book === "kalshi" ? "font-semibold text-white" : "text-slate-200"}>Kalshi (demo)</span>
        <span className="ml-2 rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">DEMO</span>
      </Link>
    </nav>
  );
}

const TABS = [
  { id: "book", label: "Book" },
  { id: "performance", label: "Performance" },
  { id: "trade", label: "Trade" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function TabNav({ book, tab }: { book: string; tab: TabId }) {
  return (
    <nav aria-label="Portfolio sections" className="mt-3 flex gap-1 border-b border-slate-800">
      {TABS.map((t) => {
        const active = t.id === tab;
        return (
          <Link key={t.id} to={`/portfolio?book=${book}&tab=${t.id}`} aria-current={active ? "page" : undefined}
                className={`rounded-t-lg px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${active ? "bg-slate-800 font-semibold text-white" : "text-slate-400 hover:text-white"}`}>
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Portfolio() {
  const [searchParams] = useSearchParams();
  const rawBook = searchParams.get("book");
  const book = rawBook === "big" ? "big" : rawBook === "kalshi" ? "kalshi" : "main";
  return (
    <div className="mx-auto max-w-[100rem] px-4 py-5 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-white">Portfolio</h1>
        <BookTabs book={book} />
      </div>
      {book === "kalshi" ? <KalshiDemoBook /> : <AlpacaBook book={book} />}
    </div>
  );
}

function AlpacaBook({ book }: { book: string }) {
  const [searchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab: TabId = rawTab === "performance" ? "performance" : rawTab === "trade" ? "trade" : "book";
  const { data, error, loading, lastUpdatedAt, stale } = useApi<PortfolioPayload>(
    `/api/portfolio?book=${book}`, REFRESH_MS);
  type IdeaRow = { id: number; title: string; size_pct: number | null; live_at: string | null; killed_at: string | null; auto_orders: boolean; books?: { big?: { live_at: string | null; size_pct: number | null; auto_orders: boolean; killed_at: string | null } } };
  const [ideaRows, setIdeaRows] = useState<IdeaRow[]>([]);
  useEffect(() => {
    let cancelled = false;
    // Admin only: a signed-out visitor gets a 401 and simply sees no list.
    adminJson<IdeaRow[]>("/api/workshop/ideas")
      .then((rows) => { if (!cancelled) setIdeaRows(Array.isArray(rows) ? rows : []); })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  // The ideas trading on the book in view: main reads the idea rows, the $1M book
  // reads its own activations -- different ideas at different sizes per book.
  const liveIdeas = ideaRows.flatMap((r) => {
    if (book === "big") {
      const a = r.books?.big;
      return a && a.live_at && !a.killed_at && a.auto_orders
        ? [{ id: r.id, title: r.title, size_pct: a.size_pct }] : [];
    }
    return r.live_at && !r.killed_at && r.auto_orders
      ? [{ id: r.id, title: r.title, size_pct: r.size_pct }] : [];
  });

  return (
    <>
      {loading && (
        <div className="mt-8 flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && <p className="mt-8 text-rose-300">Could not read the portfolio: {error}</p>}

      {data && data.state === "not_connected" && (
        <div className="mt-6 rounded-xl border border-slate-800 p-6">
          <div className="text-xl font-semibold text-white">Paper account not connected</div>
          <p className="mt-1 max-w-prose text-sm text-slate-400">
            The paper trading account is not linked yet. Numbers appear here from its first snapshot, never before.
          </p>
        </div>
      )}

      {data && data.state !== "not_connected" && data.scoreboard && (
        <>
          <PortfolioHeader data={data} lastUpdatedAt={lastUpdatedAt} stale={stale} />
          <WarningsStrip book={book} data={data} />
          <TabNav book={book} tab={tab} />
          <div className="mt-2">
            {tab === "book" && <BookTab data={data} liveIdeas={liveIdeas} book={book} />}
            {tab === "performance" && <PerformanceTab data={data} book={book} />}
            {tab === "trade" && <TradeTab book={book} />}
          </div>
        </>
      )}
    </>
  );
}
