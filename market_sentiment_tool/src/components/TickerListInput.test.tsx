import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TickerListInput from "@/components/TickerListInput";
import { parseTickerList } from "@/lib/tickers";

describe("parseTickerList", () => {
  it("splits, trims, uppercases, dedupes", () => {
    expect(parseTickerList(" aapl, msft ,AAPL,, xom ")).toEqual(["AAPL", "MSFT", "XOM"]);
    expect(parseTickerList("")).toEqual([]);
  });
});

describe("TickerListInput", () => {
  it("lets the comma be typed: raw text survives while the parse flows live", () => {
    const onChange = vi.fn();
    render(<TickerListInput value={["XOM"]} onChange={onChange} />);
    const input = screen.getByRole("textbox") as HTMLInputElement;
    fireEvent.focus(input);
    // The reported bug: typing the comma used to delete it on the spot,
    // because the field re-rendered from the parse. Now the parse flows to
    // the parent but the display stays the raw text.
    fireEvent.change(input, { target: { value: "XOM, CVX," } });
    expect(input.value).toBe("XOM, CVX,");
    expect(onChange).toHaveBeenLastCalledWith(["XOM", "CVX"]);
    fireEvent.blur(input);
    expect(input.value).toBe("XOM, CVX");
  });

  it("resyncs from the parent when not editing (a drafted spec arriving)", () => {
    const { rerender } = render(<TickerListInput value={[]} onChange={() => {}} />);
    rerender(<TickerListInput value={["AAPL", "MSFT"]} onChange={() => {}} />);
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("AAPL, MSFT");
  });
});
