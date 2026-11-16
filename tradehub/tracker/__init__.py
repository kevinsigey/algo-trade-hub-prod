"""The Thesis Tracker (Thesis v6 joining ledger).

Design: docs/superpowers/specs/2026-11-16-thesis-tracker-design.md.
Schema: migration 20261115000001_thesis_tracker.sql. This package is
the joining layer the Fable audit called for: forecast cards frozen
before the print, outcomes graded by timer, trades joined to cards and
theses, and the falsifiers (Claims A/B/C) counted from those records --
never from hand-kept tallies.
"""
