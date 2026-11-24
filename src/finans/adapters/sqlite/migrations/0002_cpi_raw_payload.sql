CREATE TABLE cpi (
  series_code TEXT NOT NULL CHECK (series_code <> ''),
  period      TEXT NOT NULL CHECK (
    period GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]' AND substr(period, 6) BETWEEN '01' AND '12'
  ),
  index_value TEXT NOT NULL,
  base        TEXT,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY (series_code, period)
) STRICT, WITHOUT ROWID;

CREATE TABLE cpi_revision (
  series_code TEXT NOT NULL,
  period      TEXT NOT NULL,
  old_value   TEXT NOT NULL,
  new_value   TEXT NOT NULL,
  revised_at  TEXT NOT NULL,
  FOREIGN KEY (series_code, period) REFERENCES cpi (series_code, period)
) STRICT;

CREATE TABLE raw_payload (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL CHECK (source <> ''),
  request_key TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  body        BLOB NOT NULL
) STRICT;

ALTER TABLE price_revision ADD COLUMN old_source TEXT CHECK (old_source IN ('tefas', 'manual'));
ALTER TABLE price_revision ADD COLUMN new_source TEXT CHECK (new_source IN ('tefas', 'manual'));
