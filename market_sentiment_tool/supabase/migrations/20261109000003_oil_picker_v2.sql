-- Picker v2 (spec 2026-11-09-hourly-best-strike-picker-v2-amendment):
-- freezes record what they saw. freeze_kind separates the T-30 and T-10
-- pick sets (legacy rows default to 'T-30', their only kind);
-- picker_version is 'v2' on new freezes and NULL on the legacy control
-- segment; ours_cal is the calibrated side probability the v2 test used
-- (ours keeps its v1 meaning, the raw side probability); yes_bid /
-- yes_ask are the picked row's quotes; sigma_h and minutes_to_close are
-- exact at the freeze; edge_net_pts is the fee-net edge the pick ranked
-- on; calib_map_version names the calibration map that produced it.
ALTER TABLE public.oil_itm_lines
  ADD COLUMN IF NOT EXISTS freeze_kind text NOT NULL DEFAULT 'T-30',
  ADD COLUMN IF NOT EXISTS picker_version text,
  ADD COLUMN IF NOT EXISTS ours_cal numeric,
  ADD COLUMN IF NOT EXISTS yes_bid numeric,
  ADD COLUMN IF NOT EXISTS yes_ask numeric,
  ADD COLUMN IF NOT EXISTS sigma_h numeric,
  ADD COLUMN IF NOT EXISTS minutes_to_close numeric,
  ADD COLUMN IF NOT EXISTS edge_net_pts numeric,
  ADD COLUMN IF NOT EXISTS calib_map_version text;
