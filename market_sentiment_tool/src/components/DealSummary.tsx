import type { SummaryDoc } from "@/lib/deals";

// The AI deal summary rendered as a document (Kevin, 2026-11-03):
// headline, titled sections, real tables for the football field and the
// scenarios, bullets for catalysts/risks, and the takeaway set apart.
// What it replaces was the model's raw markdown sitting in a <pre>.

export default function DealSummary({ doc }: { doc: SummaryDoc }) {
  return (
    <div className="mt-2 rounded-lg bg-slate-950/70 p-4">
      <p className="text-[17px] font-semibold leading-snug text-white">{doc.headline}</p>
      <div className="mt-3 space-y-4">
        {doc.sections.map((s, i) => (
          <section key={`${s.title}-${i}`} aria-label={s.title}>
            <h4 className="text-[13px] font-semibold uppercase tracking-wide text-slate-300">{s.title}</h4>
            {s.paragraphs.map((para, j) => (
              <p key={j} className="mt-1.5 text-[15px] leading-relaxed text-slate-200">{para}</p>
            ))}
            {s.bullets.length > 0 && (
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[15px] leading-relaxed text-slate-200">
                {s.bullets.map((b, j) => <li key={j}>{b}</li>)}
              </ul>
            )}
            {s.table && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                      {s.table.columns.map((c, j) => <th key={j} className="py-1 pr-3 font-medium">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {s.table.rows.map((row, ri) => (
                      <tr key={ri} className="border-t border-slate-800/70">
                        {row.map((cell, ci) => (
                          <td key={ci} className={`py-1.5 pr-3 ${ci === 0 ? "text-slate-100" : "text-slate-300"}`}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}
      </div>
      {doc.takeaway && (
        <p className="mt-4 border-l-2 border-violet-400/70 pl-3 text-[15px] font-medium leading-relaxed text-violet-100">
          {doc.takeaway}
        </p>
      )}
    </div>
  );
}
