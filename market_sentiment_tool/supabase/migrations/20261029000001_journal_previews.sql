-- Live preview of the next monthly release (jobs, CPI): the same models run ahead of the freeze window.
-- Not part of the scored record: no trigger ties it to journal_forecasts, rows are replaced on every run.
-- Written by the service-role journal job; read through GET /api/journal/previews. Idempotent.
CREATE TABLE IF NOT EXISTS journal_previews (
  target             text NOT NULL,
  forecaster         text NOT NULL,
  forecaster_version text NOT NULL,
  family             text NOT NULL,
  close_at           timestamptz NOT NULL,
  probability        double precision NOT NULL,
  market_prob        double precision,
  payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at        timestamptz NOT NULL,
  PRIMARY KEY (target, forecaster, forecaster_version)
);
ALTER TABLE journal_previews ENABLE ROW LEVEL SECURITY;
