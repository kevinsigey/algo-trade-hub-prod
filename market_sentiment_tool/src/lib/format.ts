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

const CT_DATE_TIME_YEAR = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", weekday: "short", month: "short", day: "numeric",
  year: "numeric", hour: "numeric", minute: "2-digit",
});

const CT_DATE_YEAR = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", month: "short", day: "numeric", year: "numeric",
});

/** "Mon Nov 9, 2026, 9:44 PM CT" — recorded timestamps carry their year
 * (reliability pass F5: a bare "Nov 9" hid which year's snapshot a sheet
 * belonged to). */
export const ctDateTimeYear = (iso: string) => `${CT_DATE_TIME_YEAR.format(new Date(iso))} CT`;

/** "Nov 9, 2026" */
export const ctDateYear = (iso: string) => CT_DATE_YEAR.format(new Date(iso));

/** "$77,844" -- whole dollars at $10 and up, cents below. */
export const usd = (v: number | null | undefined) => {
  if (v == null) return "—";
  const digits = v < 10 ? 2 : 0;
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};
