import { useEffect, useId, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
// Pages
import Overview from "@/pages/Overview";
import Crypto from "@/pages/Crypto";
import SportsEdges from "@/pages/SportsEdges";
import Macro from "@/pages/Macro";
import JobsNowcast from "@/pages/JobsNowcast";
import Cpi from "@/pages/Cpi";
import OilLayout from "@/components/OilLayout";
import Hormuz from "@/pages/Hormuz";
import Oil from "@/pages/Oil";
import Journal from "@/pages/Journal";
import Health from "@/pages/Health";
import MachineKeys from "@/pages/MachineKeys";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import Weather from "@/pages/Weather";
import { NoOrdersBanner } from "@/components/NoOrdersBanner";
import Portfolio from "@/pages/Portfolio";
import ClosedTrades from "@/pages/ClosedTrades";
import IdeaRecord from "@/pages/IdeaRecord";
import Ideas from "@/pages/Ideas";
import Login, { RecoveryRedirect } from "@/pages/Login";
import { GoatCounterTracker } from "@/components/GoatCounterTracker";
import Workshop from "@/pages/Workshop";
import Screening from "@/pages/Screening";
import Deals from "@/pages/Deals";
import WorkshopIdea from "@/pages/WorkshopIdea";
import Debates from "@/pages/Debates";
import Strategies from "@/pages/Strategies";
import { RequireAdmin, useAdminSession } from "@/components/RequireAdmin";
import { useApi } from "@/hooks/usePaperPortfolio";
import { fmtUsd, stateLabel, type PortfolioPayload } from "@/lib/paperPortfolio";
import { supabase } from "@/lib/supabase";
import {
  Activity,
  BarChart3,
  BookOpen,
  Briefcase,
  ChevronDown,
  House,
  CloudSun,
  FlaskConical,
  Fuel,
  Ship,
  Handshake,
  HeartPulse,
  History,
  KeyRound,
  Landmark,
  LayoutDashboard,
  Lightbulb,
  LineChart,
  ListFilter,
  Lock,
  LogOut,
  Menu,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Target,
  Trophy,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";

type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean; sub?: boolean };

/**
 * The nav, once, as data: the rail, the collapsed rail and the phone overlay all draw it.
 *
 * Kevin, 2026-11-05: the old five groups had grown to twenty links, with the Overview missing and
 * research pages split between "Ideas" and "Predictions". Four groups now, in the order a visit
 * runs: what the money is doing, the markets being read, the graded record, the operator pages.
 * Every page keeps its URL, so the shared global nav's links still work.
 */
const NAV: { label: string; items: NavItem[] }[] = [
  { label: "Trading", items: [
    { to: "/", label: "Overview", icon: House, end: true },
    { to: "/portfolio", label: "Portfolio", icon: LayoutDashboard },
    { to: "/portfolio/closed", label: "Trades and Orders", icon: History },
    { to: "/strategies", label: "Strategies", icon: Target },
    { to: "/ideas", label: "Ideas", icon: Lightbulb },
    { to: "/workshop", label: "Workshop", icon: FlaskConical },
  ] },
  { label: "Markets", items: [
    { to: "/oil", label: "Oil", icon: Fuel, end: true },
    { to: "/oil/hormuz", label: "Hormuz tracker", icon: Ship, sub: true },
    { to: "/crypto", label: "Crypto research", icon: LineChart },
    { to: "/macro", label: "Macro predictions", icon: Landmark },
    { to: "/weather", label: "Weather", icon: CloudSun },
    { to: "/sports", label: "Sports", icon: Trophy },
  ] },
  { label: "Track record", items: [
    { to: "/journal", label: "Model Tracker", icon: BookOpen },
  ] },
  { label: "Admin", items: [
    { to: "/screening", label: "Screening", icon: ListFilter },
    { to: "/deals", label: "Deals and IPOs", icon: Handshake },
    { to: "/debates", label: "Agent debates", icon: MessagesSquare },
    { to: "/health", label: "Health", icon: HeartPulse },
    { to: "/machine-keys", label: "Machine keys", icon: KeyRound },
  ] },
];

/** A per-browser preference. Storage can be missing or blocked (private window, preview); the nav works without it. */
function useStored<T>(key: string, initial: T, valid: (v: unknown) => v is T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      const parsed: unknown = raw == null ? initial : JSON.parse(raw);
      return valid(parsed) ? parsed : initial;  // a hand-edited or old value never breaks the nav
    } catch {
      return initial;
    }
  });
  const save = (v: T) => {
    setValue(v);
    try { window.localStorage.setItem(key, JSON.stringify(v)); } catch { /* the choice lasts this visit */ }
  };
  return [value, save];
}

const itemClass = (collapsed: boolean, sub?: boolean) => ({ isActive }: { isActive: boolean }) =>
  [
    "group/link relative flex items-center rounded-lg text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400",
    collapsed ? "h-10 w-10 justify-center" : `gap-3 px-3 py-2 ${sub ? "ml-5 py-1.5" : ""}`,
    isActive ? "bg-slate-800/80 text-white font-semibold" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100",
  ].join(" ");

function NavEntry({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon;
  return (
    <NavLink to={item.to} end={item.end} className={itemClass(collapsed, item.sub)} title={collapsed ? item.label : undefined}>
      {({ isActive }) => (
        <>
          {isActive && !collapsed && <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-emerald-400" />}
          <Icon className={`${item.sub && !collapsed ? "h-4 w-4" : "h-[18px] w-[18px]"} shrink-0 ${isActive ? "text-emerald-300" : ""}`} aria-hidden="true" />
          <span className={collapsed ? "sr-only" : "truncate"}>{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

function compactUsd(v: number): string {
  return Math.abs(v) >= 1_000_000 ? `$${(v / 1_000_000).toFixed(2)}M` : `$${(v / 1000).toFixed(1)}k`;
}

/**
 * The nav body, shared by the rail and the phone overlay.
 *
 * `collapsed` draws icons only (names stay for screen readers and as hover titles); `onToggle` is
 * the rail's collapse control, which the overlay does not have. `onNavigate` is the overlay's way
 * of saying "the reader picked a page": the drawer closes, so a new page is never read through it.
 */
const SidebarBody = ({ onNavigate, collapsed = false, onToggle }: {
  onNavigate?: () => void; collapsed?: boolean; onToggle?: () => void;
}) => {
  const { data, loading } = useApi<PortfolioPayload>("/api/portfolio");
  const admin = useAdminSession();
  const [closed, setClosed] = useStored<string[]>("atr:nav-closed-groups", [],
    (v): v is string[] => Array.isArray(v) && v.every((g) => typeof g === "string"));
  const uid = useId();
  // A payload without a scoreboard (an older server, a proxy error page) reads as not connected, never as a crash.
  const book = data?.scoreboard && data.state !== "not_connected" ? data : null;
  const toggleGroup = (label: string) =>
    setClosed(closed.includes(label) ? closed.filter((g) => g !== label) : [...closed, label]);
  const SignIcon = admin === "admin" ? LogOut : Lock;

  return (
    <>
      <div className={`flex items-center ${collapsed ? "flex-col gap-3 px-2 py-5" : "gap-3 px-5 py-5"}`}>
        <NavLink to="/" onClick={onNavigate} className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400" aria-label="Algo Trade Hub home">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-secondary">
            <Activity className="h-5 w-5 text-foreground" aria-hidden="true" />
          </span>
          {!collapsed && <span className="truncate font-display text-xl font-semibold uppercase tracking-wide text-foreground">Algo Trade Hub</span>}
        </NavLink>
        {onToggle && (
          <button type="button" onClick={onToggle} aria-pressed={collapsed}
                  aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                  className={`${collapsed ? "" : "ml-auto"} inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-900 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400`}>
            {collapsed ? <PanelLeftOpen className="h-4 w-4" aria-hidden="true" /> : <PanelLeftClose className="h-4 w-4" aria-hidden="true" />}
          </button>
        )}
      </div>

      <nav onClick={onNavigate} aria-label="Site" className={`flex-1 overflow-y-auto ${collapsed ? "flex flex-col items-center gap-1 px-2" : "space-y-4 px-3"}`}>
        {NAV.map((group, gi) => {
          const open = collapsed || !closed.includes(group.label);
          const id = `${uid}-group-${gi}`;
          return (
            <div key={group.label} className={collapsed && gi > 0 ? "mt-2 w-full border-t border-slate-800/80 pt-3 flex flex-col items-center gap-1" : collapsed ? "flex flex-col items-center gap-1" : ""}>
              {!collapsed && (
                <button type="button" onClick={(e) => { e.stopPropagation(); toggleGroup(group.label); }}
                        aria-expanded={open} aria-controls={id}
                        className="flex w-full items-center rounded-md px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 hover:text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
                  {group.label}
                  <ChevronDown className={`ml-auto h-3.5 w-3.5 transition-transform duration-200 motion-reduce:transition-none ${open ? "" : "-rotate-90"}`} aria-hidden="true" />
                </button>
              )}
              {open && (
                <div id={id} className={collapsed ? "contents" : "space-y-0.5"}>
                  {group.items.map((item) => <NavEntry key={item.to} item={item} collapsed={collapsed} />)}
                  {group.label === "Admin" && (admin === "admin" ? (
                    <button type="button" onClick={() => void supabase.auth.signOut()}
                            className={`${itemClass(collapsed)({ isActive: false })} ${collapsed ? "" : "w-full"}`} title={collapsed ? "Sign out" : undefined}>
                      <SignIcon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                      <span className={collapsed ? "sr-only" : ""}>Sign out</span>
                    </button>
                  ) : (
                    <NavEntry item={{ to: "/login", label: "Sign in", icon: Lock }} collapsed={collapsed} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className={`border-t border-slate-900 ${collapsed ? "p-2" : "p-3"}`}>
        <NavLink to="/portfolio" onClick={onNavigate}
                 title={collapsed ? (book ? `Paper account · ${stateLabel(book.state, book.as_of)}` : "Paper account") : undefined}
                 className={`block rounded-xl border border-slate-800 bg-slate-900/50 hover:border-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${collapsed ? "px-1 py-2 text-center" : "p-3"}`}>
          <div className={`flex items-center gap-2 text-xs font-medium text-slate-400 ${collapsed ? "justify-center" : ""}`}>
            <Wallet className="h-4 w-4" aria-hidden="true" />
            <span className={collapsed ? "sr-only" : ""}>Paper account</span>
            {collapsed && book && <span className="sr-only">{stateLabel(book.state, book.as_of)}</span>}
          </div>
          <div className={`mt-1 font-bold tabular-nums tracking-tight ${collapsed ? "text-[11px]" : "text-xl"} ${book ? "text-white" : "text-slate-400"}`}>
            {book ? (collapsed ? compactUsd(book.scoreboard.equity) : fmtUsd(book.scoreboard.equity, { whole: true }))
              : loading ? "—" : collapsed ? "off" : "Not connected"}
          </div>
          {book && !collapsed && <div className="mt-0.5 text-[11px] text-slate-500">{stateLabel(book.state, book.as_of)}</div>}
        </NavLink>
      </div>
    </>
  );
};

/**
 * The rail, from 768px up. It collapses to a 72px icon column (Kevin, 2026-11-05), remembered per
 * browser. Below 768px it is display:none and the menu button opens the same nav as an overlay;
 * the breakpoint is CSS, so there is no width check in JavaScript to fall out of step with it.
 */
const SidebarRail = () => {
  const [collapsed, setCollapsed] = useStored<boolean>("atr:nav-collapsed", false, (v): v is boolean => typeof v === "boolean");
  return (
    <div
      data-testid="sidebar-rail"
      data-collapsed={collapsed ? "true" : "false"}
      className={`hidden md:flex flex-col shrink-0 ${collapsed ? "w-[72px]" : "w-64"} bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0 transition-[width] duration-200 ease-out motion-reduce:transition-none`}
    >
      <SidebarBody collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
    </div>
  );
};

/**
 * The shell: the rail beside the page, and -- on a phone -- a menu button that opens the same nav
 * over the page.
 *
 * On a 375px screen the rail was two thirds of the viewport, so every page was cramped. Below
 * 768px the rail is hidden and the button opens the nav as an overlay instead; from 768px up
 * nothing changes at all, and the button is not even on the screen.
 *
 * The overlay closes on a route change (the reader asked for a page, not for a page behind a
 * drawer), on Escape and on a click on the backdrop. It is a real `<button>`, so it is reachable
 * by keyboard, and it carries `aria-expanded`, so a screen reader says whether the menu is open.
 */
export const AppShell = ({ children }: { children: React.ReactNode }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  // A route change closes the menu.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // Escape closes it, and hands the keyboard back to the button that opened it.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // The panel takes focus when it opens, so the next Tab lands on the first link inside it.
  useEffect(() => {
    if (menuOpen) overlayRef.current?.focus();
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    // Column on a phone (the menu bar sits above the page), row from 768px up (the rail sits
    // beside the page, as it always has).
    <div className="flex min-h-screen flex-col bg-slate-950 md:flex-row">
      <SidebarRail />
      {menuOpen && (
        <>
          <div
            data-testid="sidebar-backdrop"
            aria-hidden="true"
            onClick={closeMenu}
            className="md:hidden fixed inset-0 z-40 bg-slate-950/70"
          />
          <div
            id="site-menu"
            data-testid="sidebar-overlay"
            role="dialog"
            aria-label="Site menu"
            tabIndex={-1}
            ref={overlayRef}
            className="md:hidden fixed inset-y-0 left-0 z-50 flex flex-col w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen shadow-2xl"
          >
            <SidebarBody onNavigate={closeMenu} />
          </div>
        </>
      )}
      {/* The phone's way into the nav. md:hidden, so from 768px up the page starts at the top
          exactly as it always did. */}
      <div className="md:hidden sticky top-0 z-30 flex items-center gap-3 border-b border-slate-900 bg-slate-950/95 px-4 py-3">
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-800 text-slate-300 hover:bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          {menuOpen ? (
            <X className="w-5 h-5" aria-hidden="true" />
          ) : (
            <Menu className="w-5 h-5" aria-hidden="true" />
          )}
        </button>
        <span className="text-sm font-bold uppercase italic tracking-tight text-white">Algo Trade Hub</span>
      </div>
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        <NoOrdersBanner />
        {children}
      </main>
    </div>
  );
};

function Guarded({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary resetKey={useLocation().pathname}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <BrowserRouter>
      <GoatCounterTracker />
      <RecoveryRedirect />
      <AppShell>
        <Guarded>
        <Routes>
          {/* Home is the Overview (Kevin's 2026-11-01 redesign: what is live, which models moved,
              what happens next). The portfolio keeps its own page; the old /predictions overview
              duplicated the journal's standings and is retired into a redirect. */}
          <Route path="/" element={<Overview />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/portfolio/closed" element={<ClosedTrades />} />
          <Route path="/ideas" element={<Ideas />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/ideas/:id" element={<IdeaRecord />} />
          <Route path="/predictions" element={<Navigate to="/" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/workshop" element={<RequireAdmin><Workshop /></RequireAdmin>} />
          <Route path="/agent" element={<Navigate to="/ideas" replace />} />
          <Route path="/screening" element={<RequireAdmin><Screening /></RequireAdmin>} />
          <Route path="/deals" element={<RequireAdmin><Deals /></RequireAdmin>} />
          <Route path="/debates" element={<RequireAdmin><Debates /></RequireAdmin>} />
          <Route path="/workshop/:id" element={<RequireAdmin><WorkshopIdea /></RequireAdmin>} />
          {/* /lab was the Prediction Lab; the journal replaced it (v2 spec §9). A redirect, not a 404, so
              bookmarks and links keep working. */}
          <Route path="/lab" element={<Navigate to="/journal" replace />} />
          {/* Phase-3 §5: the shadow backtester is deleted (it graded a worker that stopped in
              June 2026 as if it were live). /shadow redirects to the crypto research desk --
              the destination is the crypto successor page, not the scoreboard, so the old
              collision warning does not apply. */}
          <Route path="/shadow" element={<Navigate to="/crypto" replace />} />
          <Route path="/crypto" element={<Crypto />} />
          <Route path="/journal" element={<Journal />} />
          {/* Merged into the Model Tracker (Kevin's call, 2026-11-02): the scoreboard and the
              models catalogue were two admin tabs presenting the /api/scoreboard dataset next
              to the Tracker's forward record. Both names now land on the Tracker's Backtests
              tab; the RequireAdmin wrap stays, so a signed-out visit still meets the login
              wall it met before, and the tab itself is the board. */}
          <Route path="/models" element={<RequireAdmin><Navigate to="/journal?view=backtests" replace /></RequireAdmin>} />
          {/* The engine scoreboard, canonically at /scoreboard.
              `/engines` was the other candidate and was rejected: /models already lists every
              engine one row at a time, so /engines would have been a SECOND route that means "the
              engines", differing only in depth. That is the same collision this branch exists to
              close, one level down. `/scoreboard` names the artifact rather than its contents, so
              it takes a new engine without the name going stale, and it already matches the
              endpoint (/api/scoreboard) and the file (Scoreboard.tsx), so it costs no rename. */}
          <Route path="/scoreboard" element={<RequireAdmin><Navigate to="/journal?view=backtests" replace /></RequireAdmin>} />
          {/* `/shadow-scoreboard` -> `/scoreboard`, permanently.
              The owner's approval for this page was literally called "the shadow scoreboard", so
              that string is a name people will type. A redirect makes the NAME work without making
              it the NAME, which is the whole distinction: "shadow" already means two things in
              this product -- the crypto timeline and the not-promoted gate status -- and the engine
              scoreboard is about neither. An earlier revision of this branch made
              /shadow-scoreboard canonical, which left the ambiguity in a route instead of a nav
              label, where it is expensive to change. It is a redirect here and nothing else.
              Same component, same /api/scoreboard read, address bar updated to the real path. */}
          <Route path="/shadow-scoreboard" element={<Navigate to="/journal?view=backtests" replace />} />
          <Route path="/sports" element={<SportsEdges />} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/jobs" element={<JobsNowcast />} />
          <Route path="/cpi" element={<Cpi />} />
          <Route path="/oil" element={<OilLayout />}>
            <Route index element={<Oil />} />
            <Route path="hormuz" element={<Hormuz />} />
          </Route>
          <Route path="/health" element={<RequireAdmin><Health /></RequireAdmin>} />
          <Route path="/machine-keys" element={<RequireAdmin><MachineKeys /></RequireAdmin>} />
          <Route path="/weather" element={<Weather />} />
        </Routes>
        </Guarded>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
