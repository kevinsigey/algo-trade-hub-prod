import type { ReactNode } from "react";

import { Panel } from "@/components/Panel";
import { fmtUsd } from "@/lib/paperPortfolio";

/** The page's card shell (the Panel with the Portfolio page's prop names). */
export function Box({ title, right, children, className = "", full }: {
  title: string; right?: ReactNode; children: ReactNode; className?: string; full?: ReactNode;
}) {
  return <Panel title={title} meta={right} full={full} className={className}>{children}</Panel>;
}

export const money = (v: number | null | undefined) => fmtUsd(v, { whole: true });
export const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
export const price = (v: number | null | undefined) => fmtUsd(v);

/** The Portfolio page's 30-second live refresh cycle (2026-11-12 redesign). */
export const REFRESH_MS = 30_000;
