-- ASTRA
-- Основной индекс временной истории каналов.
--
-- Используется:
-- - online inference;
-- - ML training;
-- - поиск последнего события.

CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_ext_journal_sensor_time_event
ON ext_journal_prepared (
    sensor_id,
    occurred_at,
    event_id
);
