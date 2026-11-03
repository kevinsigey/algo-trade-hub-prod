import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import DealSummary from "@/components/DealSummary";
import type { SummaryDoc } from "@/lib/deals";

const DOC: SummaryDoc = {
  headline: "Anthropic at $97.78 vs a $170 talk midpoint",
  sections: [
    { title: "The deal", paragraphs: ["A draft paragraph."], bullets: [], table: null },
    { title: "Valuation", paragraphs: [], bullets: [],
      table: { columns: ["Case", "Per share"], rows: [["Bear", "$61.00"], ["PW", "$97.78"]] } },
    { title: "Risks", paragraphs: [], bullets: ["Entry fails the test."], table: null },
  ],
  takeaway: "Pass at the talk.",
};

describe("DealSummary", () => {
  it("renders the document: headline, sections, a real table, bullets, takeaway", () => {
    const { container } = render(<DealSummary doc={DOC} />);
    expect(screen.getByText(/Anthropic at \$97.78/)).toBeInTheDocument();
    expect(screen.getByText("The deal")).toBeInTheDocument();
    expect(screen.getByText("A draft paragraph.")).toBeInTheDocument();
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table!.textContent).toContain("$97.78");
    expect(screen.getByText("Entry fails the test.")).toBeInTheDocument();
    expect(screen.getByText("Pass at the talk.")).toBeInTheDocument();
    // No raw markdown artifacts anywhere in the render.
    expect(container.textContent).not.toContain("##");
    expect(container.querySelector("pre")).toBeNull();
  });
});
