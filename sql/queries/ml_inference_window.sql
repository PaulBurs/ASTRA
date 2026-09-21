-- ASTRA ML inference query.
--
-- :sensor_id, :start, :end, :limit
-- являются именованными параметрами SQLAlchemy.

SELECT
    ид_события AS event_id,
    ид_канала_данных AS sensor_id,
    дата_время_события AS occurred_at,
    тип_значения AS value_type,
    значение_число AS numeric_value,
    значение_дата_время AS datetime_value,
    значение_текст AS text_value
FROM ext_journal_prepared
WHERE ид_канала_данных = :sensor_id
  AND дата_время_события >= :start
  AND дата_время_события <= :end
ORDER BY
    дата_время_события DESC,
    ид_события DESC
LIMIT :limit;
