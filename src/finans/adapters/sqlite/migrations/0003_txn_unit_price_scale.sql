ALTER TABLE txn ADD COLUMN unit_price_scale INTEGER CHECK (unit_price_scale BETWEEN 0 AND 28);
