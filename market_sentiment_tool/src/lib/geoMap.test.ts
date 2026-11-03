import { describe, expect, it } from "vitest";

import { frameFor, worldPx, zoomForWidth } from "@/lib/geoMap";

describe("geoMap slippy math", () => {
  it("projects the origin to the world center at zoom 0", () => {
    const p = worldPx(0, 0, 0);
    expect(Math.round(p.x)).toBe(128);
    expect(Math.round(p.y)).toBe(128);
  });

  it("fits the Hormuz bbox into ~960px at a sane zoom with covering tiles", () => {
    const bbox: [number, number, number, number] = [24.0, 50.5, 28.5, 59.5];
    const z = zoomForWidth(bbox, 960);
    expect(z).toBeGreaterThanOrEqual(6);
    expect(z).toBeLessThanOrEqual(8);
    const frame = frameFor(bbox, 960);
    expect(frame.width).toBeLessThanOrEqual(960);
    expect(frame.height).toBeGreaterThan(300);
    expect(frame.tiles.length).toBeGreaterThanOrEqual(12);
    // the gate (26.1-26.8N, 56.0-56.9E) projects inside the frame
    const gate = frame.boxRect([26.1, 56.0, 26.8, 56.9]);
    expect(gate.left).toBeGreaterThan(0);
    expect(gate.left + gate.width).toBeLessThanOrEqual(frame.width + 1);
    expect(gate.top).toBeGreaterThan(0);
    expect(gate.top + gate.height).toBeLessThanOrEqual(frame.height + 1);
  });
});
