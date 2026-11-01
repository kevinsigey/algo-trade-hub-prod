/**
 * One timestamp style and one money format for the phase-3 pages (§6):
 * every clock time on the Macro / Health / Weather / Sports / Crypto /
 * Portfolio pages reads in America/Chicago with a CT suffix, and every
 * dollar figure goes through `usd`. Dates without times stay dates; this
 * module only owns instants and money.
 */

const CT_TIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", hour: "numeric", minute: "2-digit",
});

const CT_DATE_TIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", weekday: "short", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit",
});

/** "4:45 PM CT" */
export const ctTime = (iso: string) => `${CT_TIME.format(new Date(iso))} CT`;

/** "Mon Nov 2, 4:45 PM CT" */
export const ctDateTime = (iso: string) => `${CT_DATE_TIME.format(new Date(iso))} CT`;

/** "$77,844" -- whole dollars at $10 and up, cents below. */
export const usd = (v: number | null | undefined) => {
  if (v == null) return "—";
  const digits = v < 10 ? 2 : 0;
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};
