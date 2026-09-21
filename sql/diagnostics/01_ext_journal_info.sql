-- ASTRA
-- Диагностика таблицы ext_journal_prepared.
-- Только чтение. Никаких изменений БД.

SELECT
    to_regclass('public.ext_journal_prepared')
        AS ext_journal_table;


SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_name = 'ext_journal_prepared'
ORDER BY table_schema;


SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'ext_journal_prepared'
ORDER BY ordinal_position;


SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'ext_journal_prepared'
ORDER BY indexname;
