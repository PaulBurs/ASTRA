-- Последнее событие конкретного канала.

SELECT
    ид_события AS event_id,
    дата_время_события AS occurred_at
FROM ext_journal_prepared
WHERE ид_канала_данных = :sensor_id
ORDER BY
    дата_время_события DESC,
    ид_события DESC
LIMIT 1;
