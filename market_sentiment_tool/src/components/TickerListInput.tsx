import { useEffect, useRef, useState } from "react";
import { parseTickerList } from "@/lib/tickers";

/**
 * A comma-separated ticker list that can actually be typed into.
 *
 * The inputs this replaces parsed on every keystroke
 * (`value.split(",").map(trim).filter(Boolean)` written straight back as the
 * input's value), so the comma itself was filtered out of the re-rendered
 * string the moment it was typed -- a second ticker could never be added.
 * This component holds the RAW text as its own state, decoupled from the
 * parsed list: every keystroke updates the parent with the parse of what's
 * typed so far (split on commas, trim, uppercase, drop empties and
 * duplicates), but the field keeps displaying the raw text -- the comma
 * survives because the display never re-renders from the parse. Blur (or
 * Enter) only tidies the text to the canonical "A, B, C" form.
 */
export default function TickerListInput({
  value, onChange, disabled, className, placeholder,
}: {
  value: string[];
  onChange: (tickers: string[]) => void;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
}) {
  const [text, setText] = useState(() => value.join(", "));
  const editing = useRef(false);

  // Resync from the parent when the list changes outside this field (a draft
  // arriving, a reset) -- but never mid-edit, which is the bug being fixed.
  useEffect(() => {
    if (!editing.current) setText(value.join(", "));
  }, [value]);

  const commit = () => {
    editing.current = false;
    setText(parseTickerList(text).join(", "));
  };

  return (
    <input
      className={className}
      disabled={disabled}
      placeholder={placeholder ?? "e.g. XOM, CVX"}
      value={text}
      onFocus={() => { editing.current = true; }}
      onChange={(e) => { setText(e.target.value); onChange(parseTickerList(e.target.value)); }}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
    />
  );
}
