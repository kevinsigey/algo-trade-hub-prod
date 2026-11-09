import { NavLink, Outlet } from "react-router-dom";

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `-mb-px border-b-2 px-1 pb-2 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-300 ${
    isActive ? "border-amber-400 text-white" : "border-transparent text-slate-400 hover:text-slate-200"}`;

/** The Commodities section: live predictions on one tab, the Hormuz tracker on its own. */
export default function OilLayout() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Commodities</h1>
        <nav aria-label="Commodities sections" className="mt-4 flex gap-6 border-b border-slate-800">
          <NavLink to="/oil" end className={tabClass}>Live predictions</NavLink>
          <NavLink to="/oil/hormuz" className={tabClass}>Hormuz tracker</NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
