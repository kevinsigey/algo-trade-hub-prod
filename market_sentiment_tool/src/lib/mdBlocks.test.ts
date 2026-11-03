import { describe, expect, it } from "vitest";

import { parseMarkdown } from "@/lib/mdBlocks";

describe("parseMarkdown", () => {
  it("parses headings, paragraphs, bullets and pipe tables", () => {
    const md = [
      "# GOOGL Report", "",
      "Revenue growth is **robust** and `clean`.", "",
      "- First point", "- Second point", "",
      "| Case | Price |", "| --- | --- |", "| Bear | $61 |", "| Bull | $120 |", "",
      "Closing line.",
    ].join("\n");
    const blocks = parseMarkdown(md);
    expect(blocks[0]).toEqual({ type: "heading", text: "GOOGL Report" });
    expect(blocks[1]).toEqual({ type: "para", text: "Revenue growth is robust and clean." });
    expect(blocks[2]).toEqual({ type: "bullets", items: ["First point", "Second point"] });
    expect(blocks[3]).toEqual({ type: "table", columns: ["Case", "Price"], rows: [["Bear", "$61"], ["Bull", "$120"]] });
    expect(blocks[4]).toEqual({ type: "para", text: "Closing line." });
  });

  it("flattens label-style framework text and survives junk", () => {
    const blocks = parseMarkdown("**Action**: Sell **Entry Price**: 295.0");
    expect(blocks).toEqual([{ type: "para", text: "Action: Sell Entry Price: 295.0" }]);
    expect(parseMarkdown("")).toEqual([]);
    expect(parseMarkdown("not recorded")).toEqual([{ type: "para", text: "not recorded" }]);
  });

  it("treats numbered lines as bullets and code fences as prose", () => {
    const blocks = parseMarkdown("1. one\n2. two\n\n```\ncode line\n```");
    expect(blocks[0]).toEqual({ type: "bullets", items: ["one", "two"] });
    expect(blocks[1]).toEqual({ type: "para", text: "code line" });
  });
});
