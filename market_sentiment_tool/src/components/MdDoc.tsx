import { parseMarkdown, type MdBlock } from "@/lib/mdBlocks";

// Renders markdown (a debate report, a case section) as a formatted
// document instead of a raw <pre> dump: headings as section titles,
// pipe tables as real tables, bullets as lists, prose as paragraphs.
// The visual language follows DealSummary (Kevin, 2026-11-03).

export function Blocks({ blocks }: { blocks: MdBlock[] }) {
  return (
    <div className="space-y-2.5">
      {blocks.map((b, i) => {
        if (b.type === "heading") {
          return (
            <h5 key={i} className="pt-1 text-[13px] font-semibold uppercase tracking-wide text-slate-300">
              {b.text}
            </h5>
          );
        }
        if (b.type === "bullets") {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-200">
              {b.items.map((item, j) => <li key={j}>{item}</li>)}
            </ul>
          );
        }
        if (b.type === "table") {
          return (
            <div key={i} className="overflow-x-auto">
              <table className="w-full text-sm tabular-nums">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                    {b.columns.map((c, j) => <th key={j} className="py-1 pr-3 font-medium">{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, ri) => (
                    <tr key={ri} className="border-t border-slate-800/70">
                      {row.map((cell, ci) => (
                        <td key={ci} className={`py-1.5 pr-3 ${ci === 0 ? "text-slate-100" : "text-slate-300"}`}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return <p key={i} className="text-sm leading-relaxed text-slate-200">{b.text}</p>;
      })}
    </div>
  );
}

export default function MdDoc({ markdown }: { markdown: string }) {
  return <Blocks blocks={parseMarkdown(markdown)} />;
}
