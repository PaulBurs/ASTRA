-- ASTRA
-- Общая инвентаризация PostgreSQL.
-- Только чтение.

-- Текущая БД и пользователь.
SELECT
    current_database() AS database_name,
    current_user AS database_user;


-- Пользовательские схемы.
SELECT
    schema_name
FROM information_schema.schemata
WHERE schema_name NOT IN (
    'pg_catalog',
    'information_schema'
)
ORDER BY schema_name;


-- Пользовательские таблицы.
SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_schema NOT IN (
    'pg_catalog',
    'information_schema'
)
ORDER BY
    table_schema,
    table_name;


-- Представления.
SELECT
    table_schema,
    table_name
FROM information_schema.views
WHERE table_schema NOT IN (
    'pg_catalog',
    'information_schema'
)
ORDER BY
    table_schema,
    table_name;


-- Размеры пользовательских таблиц.
SELECT
    schemaname,
    relname AS table_name,
    pg_size_pretty(
        pg_total_relation_size(
            quote_ident(schemaname)
            || '.'
            || quote_ident(relname)
        )
    ) AS total_size
FROM pg_stat_user_tables
ORDER BY
    pg_total_relation_size(
        quote_ident(schemaname)
        || '.'
        || quote_ident(relname)
    ) DESC;
