-- Trading system phase 2, diagnostics pack (spec 2026-11-01 §6.1): one nullable
-- JSONB column on backtest_runs carrying the run's measured diagnostics --
-- per-feature stationarity/zero screening and residual Ljung-Box / ARCH-LM
-- results. Measurement only: nothing reads this column to gate, promote, or
-- refuse anything. Nullable because engines that do not compute diagnostics
-- record NULL, which readers render as "not measured", never as "clean".

alter table public.backtest_runs
  add column if not exists diagnostics jsonb;
