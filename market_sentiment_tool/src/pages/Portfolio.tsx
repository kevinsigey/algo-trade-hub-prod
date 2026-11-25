import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { KalshiBox, KalshiMain, useKalshiPilot, type KalshiRead } from "@/pages/KalshiLiveBook";
import { useApi } from "@/hooks/usePaperPortfolio";
import type { BookHeadline, BooksPayload, PortfolioPayload } from "@/lib/paperPortfolio";
import { adminCall, REFRESH_MS } from "@/pages/portfolio/shared";
import { WarningsStrip } from "@/pages/portfolio/Header";
import { AccountBox, BookSelector, type PaperRead } from "@/pages/portfolio/Rail";
import PaperMain, { type OpenCard } from "@/pages/portfolio/Main";

/** The Portfolio page (2026-11-25 redesign): a left column whose book cards are
 * the three-book summary, with the selected book's account box under them; the
 * main area holds the selected book's Performance and Positions cards and, for
 * the paper books, a Trade card along the bottom. The book is `?book=`; an old
 * `?tab=` link opens the matching card's full view. Everything refreshes on a
 * 30-second cycle while the tab is visible. */

const DEFAULT_BOOKS = [{ book: "main", label: "Main book" }, { book: "big", label: "$1M book" }] as BookHeadline[];

/** The card an old `?tab=` link meant: Book was Positions. */
const TAB_CARD: Record<string, OpenCard> = { book: "positions", performance: "performance", trade: "trade" };

export default function Portfolio() {
  const [searchParams] = useSearchParams();
  const rawBook = searchParams.get("book");
  const book = rawBook === "big" ? "big" : rawBook === "kalshi" ? "kalshi" : "main";
  const open = TAB_CARD[searchParams.get("tab") ?? ""];

  const { data: headlines } = useApi<BooksPayload>("/api/portfolio/books");
  const books = Array.isArray(headlines?.books) && headlines.books.length ? headlines.books : DEFAULT_BOOKS;
  // Both paper books are read so the selector can summarise them; the selected one drives the page.
  const main = useApi<PortfolioPayload>("/api/portfolio?book=main", REFRESH_MS);
  const big = useApi<PortfolioPayload>("/api/portfolio?book=big", REFRESH_MS);
  const kalshi = useKalshiPilot();
  const paper: Record<string, PaperRead> = { main, big };

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-3 md:px-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <h1 className="text-xl font-bold md:text-2xl tracking-tight text-white">Portfolio</h1>
        {book !== "kalshi" && paper[book].data?.scoreboard && paper[book].data?.state !== "not_connected" && (
          <WarningsStrip book={book} data={paper[book].data!} />
        )}
      </div>
      <div className="mt-2 grid gap-2 md:mt-3 md:gap-3 md:grid-cols-[18.5rem_minmax(0,1fr)]">
        <aside aria-label="Selected book" className="min-w-0 space-y-2 md:self-start">
          <BookSelector book={book} books={books} paper={paper} kalshi={kalshi} />
          {book === "kalshi" ? <KalshiBox k={kalshi} /> : <AccountBox read={paper[book]} />}
        </aside>
        <div className="flex min-w-0 flex-col">
          {book === "kalshi"
            ? <KalshiView k={kalshi} open={open === "performance" || open === "positions" ? open : undefined} />
            : <PaperView book={book} read={paper[book]} error={(book === "big" ? big : main).error} open={open} />}
        </div>
      </div>
    </div>
  );
}

function KalshiView({ k, open }: { k: KalshiRead; open?: "performance" | "positions" }) {
  // The account box already says why there is nothing to show (admin only, unreadable).
  return k.pilot ? <KalshiMain k={k} open={open} /> : null;
}

type IdeaRow = { id: number; title: string; size_pct: number | null; live_at: string | null; killed_at: string | null; auto_orders: boolean; books?: { big?: { live_at: string | null; size_pct: number | null; auto_orders: boolean; killed_at: string | null } } };

function useLiveIdeas(book: string) {
  const [ideaRows, setIdeaRows] = useState<IdeaRow[]>([]);
  useEffect(() => {
    let cancelled = false;
    // Admin only: a signed-out visitor gets a 401 and simply sees no list.
    adminCall<IdeaRow[]>("/api/workshop/ideas")
      .then((rows) => { if (!cancelled) setIdeaRows(Array.isArray(rows) ? rows : []); })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  // The ideas trading on the book in view: main reads the idea rows, the $1M book
  // reads its own activations -- different ideas at different sizes per book.
  return ideaRows.flatMap((r) => {
    if (book === "big") {
      const a = r.books?.big;
      return a && a.live_at && !a.killed_at && a.auto_orders
        ? [{ id: r.id, title: r.title, size_pct: a.size_pct }] : [];
    }
    return r.live_at && !r.killed_at && r.auto_orders
      ? [{ id: r.id, title: r.title, size_pct: r.size_pct }] : [];
  });
}

function PaperView({ book, read, error, open }: { book: string; read: PaperRead & { error?: string | null }; error: string | null; open: OpenCard }) {
  const liveIdeas = useLiveIdeas(book);
  const { data } = read;
  return (
    <>
      {!data && !error && (
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && !data && <p className="text-rose-300">Could not read the portfolio: {error}</p>}

      {data && data.state === "not_connected" && (
        <div className="rounded-xl border border-slate-800 p-6">
          <div className="text-xl font-semibold text-white">Paper account not connected</div>
          <p className="mt-1 max-w-prose text-sm text-slate-400">
            The paper trading account is not linked yet. Numbers appear here from its first snapshot, never before.
          </p>
        </div>
      )}

      {data && data.state !== "not_connected" && data.scoreboard && (
        <PaperMain data={data} book={book} liveIdeas={liveIdeas} open={open} />
      )}
    </>
  );
}
