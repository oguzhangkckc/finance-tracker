ALTER TABLE instrument ADD COLUMN allocation INTEGER NOT NULL DEFAULT 1 CHECK (allocation IN (0, 1));

CREATE TABLE job_run (
  id           INTEGER PRIMARY KEY,
  job          TEXT NOT NULL,
  logical_date TEXT NOT NULL CHECK (date(logical_date) IS logical_date),
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL CHECK (status IN ('running', 'ok', 'partial', 'failed')),
  detail       TEXT
) STRICT;

CREATE UNIQUE INDEX job_run_ok ON job_run (job, logical_date) WHERE status = 'ok';

CREATE TABLE alert (
  fingerprint      TEXT PRIMARY KEY,
  state            TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
  direction        TEXT CHECK (direction IN ('above', 'below')),
  opened_at        TEXT NOT NULL,
  resolved_at      TEXT,
  last_notified_at TEXT,
  payload          TEXT NOT NULL,
  CHECK ((state = 'open') = (direction IS NOT NULL))
) STRICT;

CREATE TABLE alert_event (
  id          INTEGER PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('opened', 'resolved')),
  direction   TEXT NOT NULL CHECK (direction IN ('above', 'below')),
  deviation   TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  notified_at TEXT
) STRICT;

CREATE TABLE allocation_state (
  id             INTEGER PRIMARY KEY CHECK (id = 1),
  quiet_ended_on TEXT CHECK (quiet_ended_on IS NULL OR date(quiet_ended_on) IS quiet_ended_on)
) STRICT;
