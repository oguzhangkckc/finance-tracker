-- K-127: maaş günü, aylık katkı ve hedef dağılım yürürlük tarihli sürümler halinde.
-- Hedefler Decimal metinli JSON'dur; SQL'de Decimal hesabı yapılmaz.
CREATE TABLE setting_version (
  id                   INTEGER PRIMARY KEY,
  effective_from       TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
  payday               INTEGER CHECK (payday IS NULL OR payday BETWEEN 1 AND 31),
  monthly_contribution TEXT,
  targets              TEXT NOT NULL,
  source               TEXT NOT NULL CHECK (source IN ('toml', 'cli', 'web')),
  recorded_at          TEXT NOT NULL,
  cancelled_at         TEXT,
  cancel_reason        TEXT,
  CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
) STRICT;
