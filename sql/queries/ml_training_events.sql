-- ASTRA ML training query.
--
-- Реальный Python-код передаёт список sensor IDs
-- и читает результат stream/batch режимом.

SELECT
    ид_события AS event_id,
    ид_канала_данных AS sensor_id,
    дата_время_события AS occurred_at,
    тип_значения AS value_type,
    значение_число AS numeric_value,
    значение_дата_время AS datetime_value,
    значение_текст AS text_value
FROM ext_journal_prepared
WHERE ид_канала_данных IN :sensor_ids
  AND дата_время_события >= :start
  AND дата_время_события < :end
ORDER BY
    ид_канала_данных,
    дата_время_события,
    ид_события;
