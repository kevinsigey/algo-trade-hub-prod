/** Parse a comma-separated ticker list: trim, uppercase, drop empties and duplicates. */
export function parseTickerList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of text.split(",")) {
    const t = part.trim().toUpperCase();
    if (t && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}
