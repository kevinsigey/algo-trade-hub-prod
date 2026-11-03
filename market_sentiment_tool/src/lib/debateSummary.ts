/**
 * Debate-card reading helpers: pull a short summary, the trader's action, and
 * any stated price levels out of the stored debate text (Kevin, 2026-11-02:
 * the card was a wall of text -- summary first, the numbers as a visual, the
 * full text behind dropdowns).
 *
 * Everything here is extraction, never invention: a value is returned only
 * when the text states it, and unparsed text yields null / empty, so the UI
 * can simply not render the piece. The stored fields are markdown-ish
 * excerpts (see tradehub/agents/importer.py), so the parsers are tolerant of
 * `**Label**: value` shapes and give up quietly on anything else.
 */

const NOT_RECORDED = "not recorded";

/** Text worth showing: present and not the backend's missing-field placeholder. */
export function hasText(text: string | null | undefined): text is string {
  return !!text && text.trim() !== "" && text.trim().toLowerCase() !== NOT_RECORDED;
}

/** Strip the markdown noise for one-line display: heading marks, emphasis,
 * backticks, table pipes, list bullets, and the excerpt cut markers. The full
 * text is never altered -- this only feeds previews and the summary line. */
export function cleanText(text: string): string {
  return text
    .replace(/\[…\]|\[\.\.\.\]/g, " ")
    .replace(/#{1,6}\s+/g, "")
    .replace(/\*\*|__|`/g, "")
    .replace(/\*/g, "")
    .replace(/\|/g, " ")
    .replace(/^\s*[-+]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** One clean line of at most ~`max` chars, cut on a word boundary. */
export function previewLine(text: string, max = 110): string {
  const clean = cleanText(text);
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${cut.slice(0, lastSpace > max * 0.6 ? lastSpace : max).trimEnd()}…`;
}

/** At most ~`max` chars of clean text, ending on a sentence boundary when the
 * window contains one past the halfway mark; otherwise a word-boundary cut. */
export function trimToSentences(text: string, max = 280): string {
  const clean = cleanText(text);
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const sentenceEnd = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
  if (sentenceEnd > max * 0.5) return cut.slice(0, sentenceEnd + 1);
  const lastSpace = cut.lastIndexOf(" ");
  return `${cut.slice(0, lastSpace > 0 ? lastSpace : max).trimEnd()}…`;
}

/** The text after a labelled marker ("**Executive Summary**: ..."), cut at the
 * next known section label so a following field never bleeds into the extract. */
function afterMarker(text: string, marker: RegExp): string | null {
  const m = marker.exec(text);
  if (!m) return null;
  let rest = text.slice(m.index + m[0].length);
  const next = /\*\*\s*(price target|time horizon|investment thesis|position sizing|entry price|stop loss)\s*\*\*/i.exec(rest);
  if (next && next.index > 0) rest = rest.slice(0, next.index);
  return rest;
}

/**
 * The card's 2-3 line summary, extracted only: the risk panel's Executive
 * Summary when the run stated one, else the trader's Reasoning, else the
 * opening of whichever of the two texts exists.
 */
export function extractSummary(riskVerdict: string, traderRationale: string): string | null {
  if (hasText(riskVerdict)) {
    const exec = afterMarker(riskVerdict, /executive summary\*?\*?\s*:?\s*/i);
    if (exec && cleanText(exec).length > 0) return trimToSentences(exec);
  }
  if (hasText(traderRationale)) {
    const reasoning = afterMarker(traderRationale, /reasoning\*?\*?\s*:?\s*/i);
    if (reasoning && cleanText(reasoning).length > 0) return trimToSentences(reasoning);
  }
  if (hasText(riskVerdict)) return trimToSentences(riskVerdict);
  if (hasText(traderRationale)) return trimToSentences(traderRationale);
  return null;
}

export type TraderAction = "BUY" | "SELL" | "HOLD";

/** The trader's stated action: the FINAL TRANSACTION PROPOSAL line when there
 * is one, else the Action field. Anything else (Reduce, Start, ...) is not an
 * action this parser claims -- null, and the card shows no chip. */
export function parseTraderAction(traderRationale: string): TraderAction | null {
  if (!hasText(traderRationale)) return null;
  const proposal = /final transaction proposal\*?\*?\s*:?\s*\**\s*(buy|sell|hold)\b/i.exec(traderRationale);
  if (proposal) return proposal[1].toUpperCase() as TraderAction;
  const action = /\baction\*?\*?\s*:?\s*\**\s*(buy|sell|hold)\b/i.exec(traderRationale);
  if (action) return action[1].toUpperCase() as TraderAction;
  return null;
}

export interface PriceLevels {
  entry: number | null;
  stop: number | null;
  targets: number[];
}

function firstNumber(texts: string[], pattern: RegExp): number | null {
  for (const text of texts) {
    const m = pattern.exec(text);
    if (m) {
      const value = Number(m[1].replace(/,/g, ""));
      if (Number.isFinite(value) && value > 0) return value;
    }
  }
  return null;
}

/**
 * Entry / stop / target levels stated in the trader and risk texts, e.g.
 * "**Entry Price**: 295.0", "**Stop Loss**: 315.0", "Price Target: $350".
 * A field the text leaves unstated ("Price Target: not provided") or never
 * mentions stays null -- the ladder renders only what was actually stated.
 */
export function parsePriceLevels(...texts: string[]): PriceLevels {
  const usable = texts.filter(hasText);
  const entry = firstNumber(usable, /entry price[*\s:]*\$?(\d[\d,]*(?:\.\d+)?)/i);
  const stop = firstNumber(usable, /stop(?:\s*loss)?[*\s:]*\$?(\d[\d,]*(?:\.\d+)?)/i);
  const targets: number[] = [];
  const targetRe = /(?:price target|target price|\btarget)[*\s:]*\$?(\d[\d,]*(?:\.\d+)?)/gi;
  for (const text of usable) {
    for (const m of text.matchAll(targetRe)) {
      const value = Number(m[1].replace(/,/g, ""));
      if (Number.isFinite(value) && value > 0 && value !== entry && !targets.includes(value)) targets.push(value);
    }
  }
  return { entry, stop, targets };
}

/** "$295" / "$1,234.50" -- whole dollars without decimals, cents when stated. */
export function formatPrice(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: Number.isInteger(value) ? 0 : 2, maximumFractionDigits: 2 })}`;
}
