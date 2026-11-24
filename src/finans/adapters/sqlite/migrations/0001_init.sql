CREATE TABLE instrument (
  id          INTEGER PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE CHECK (code <> ''),
  kind        TEXT NOT NULL CHECK (kind IN ('TEFAS_YAT', 'TEFAS_EMK', 'TEFAS_BYF', 'MANUAL')),
  asset_class TEXT NOT NULL,
  category    TEXT,
  name        TEXT,
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
) STRICT;

CREATE TABLE txn (
  id            INTEGER PRIMARY KEY,
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  trade_date    TEXT NOT NULL CHECK (date(trade_date) IS trade_date),
  side          TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  units         TEXT NOT NULL,
  unit_price    TEXT NOT NULL,
  fee           TEXT NOT NULL DEFAULT '0',
  external_ref  TEXT,
  note          TEXT,
  created_at    TEXT NOT NULL,
  voided_at     TEXT,
  void_reason   TEXT,
  CHECK ((voided_at IS NULL) = (void_reason IS NULL))
) STRICT;

CREATE UNIQUE INDEX txn_external_ref ON txn (external_ref) WHERE voided_at IS NULL;

CREATE TABLE price (
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  price_date    TEXT NOT NULL CHECK (date(price_date) IS price_date),
  price         TEXT NOT NULL,
  source        TEXT NOT NULL CHECK (source IN ('tefas', 'manual')),
  fetched_at    TEXT NOT NULL,
  PRIMARY KEY (instrument_id, price_date)
) STRICT, WITHOUT ROWID;

CREATE TABLE price_revision (
  instrument_id INTEGER NOT NULL REFERENCES instrument(id),
  price_date    TEXT NOT NULL CHECK (date(price_date) IS price_date),
  old_price     TEXT NOT NULL,
  new_price     TEXT NOT NULL,
  revised_at    TEXT NOT NULL
) STRICT;
