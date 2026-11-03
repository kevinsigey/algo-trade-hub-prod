// A small markdown-to-blocks parser for AI-written documents (Kevin,
// 2026-11-03): the debate reports and case texts arrive as markdown and
// rendered as a raw <pre> dump -- this turns them into the blocks the
// page renders as a document: headings, paragraphs, bullet lists and
// real tables. Deliberately minimal: it handles what the framework
// actually writes (ATX headings, -/* bullets, numbered lists, pipe
// tables, bold markers, code fences) and flattens the rest to prose.

export type MdBlock =
  | { type: "heading"; text: string }
  | { type: "para"; text: string }
  | { type: "bullets"; items: string[] }
  | { type: "table"; columns: string[]; rows: string[][] };

export function cleanInline(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\s#{1,6}\s+/g, " ")
    .trim();
}

function splitRow(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => cleanInline(c));
}

const isSeparatorRow = (line: string) =>
  /^\s*\|?[\s:|-]+\|?\s*$/.test(line) && line.includes("-") && line.includes("|");

export function parseMarkdown(md: string): MdBlock[] {
  const blocks: MdBlock[] = [];
  const lines = (md || "").split("\n");
  let para: string[] = [];
  let bullets: string[] = [];
  let inFence = false;

  const flushPara = () => {
    const text = cleanInline(para.join(" "));
    if (text) blocks.push({ type: "para", text });
    para = [];
  };
  const flushBullets = () => {
    if (bullets.length) blocks.push({ type: "bullets", items: bullets });
    bullets = [];
  };
  const flush = () => { flushPara(); flushBullets(); };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trim();
    if (line.startsWith("```")) { inFence = !inFence; flush(); continue; }
    if (inFence) { if (line) para.push(line); continue; }
    if (!line) { flush(); continue; }

    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) { flush(); blocks.push({ type: "heading", text: cleanInline(heading[1]) }); continue; }

    // A pipe table: a header row followed by a separator row.
    if (line.startsWith("|") && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      flush();
      const columns = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      i--; // the for-loop advances past the last row
      blocks.push({ type: "table", columns, rows });
      continue;
    }

    const bullet = line.match(/^(?:[-*•]|\d{1,3}[.)])\s+(.*)$/);
    if (bullet) { flushPara(); bullets.push(cleanInline(bullet[1])); continue; }

    flushBullets();
    para.push(line);
  }
  flush();
  return blocks;
}
