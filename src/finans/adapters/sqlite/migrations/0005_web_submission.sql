-- K-126: web onay formunun tek kullanımlık nonce'u; işlemle aynı veritabanı işleminde yazılır.
CREATE TABLE web_submission (
  nonce   TEXT PRIMARY KEY CHECK (length(nonce) BETWEEN 16 AND 64),
  ref     TEXT NOT NULL,
  used_at TEXT NOT NULL
) STRICT;
