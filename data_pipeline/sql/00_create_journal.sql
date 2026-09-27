-- =====================================================================
-- 00_create_journal.sql
-- Создаёт пустую таблицу журнала public.ext_journal_prepared с той же структурой,
-- что в исходной БД организаторов (партиции по годам 2019-2026).
-- Запускать ОДИН раз перед загрузкой ext_journal_prepared.csv.
-- ВНИМАНИЕ: DROP удалит уже загруженный журнал, если он есть.
-- =====================================================================
DROP TABLE IF EXISTS public.ext_journal_prepared CASCADE;

CREATE TABLE public.ext_journal_prepared (
    "ид_события"            bigint,
    "ид_канала_данных"      bigint,
    "тревожное_raw"         text,
    "значение_датчика_raw"  text,
    "дата_время_события"    timestamp without time zone,
    "тип_значения"          text,
    "значение_число"        numeric,
    "значение_дата_время"   timestamp without time zone,
    "значение_текст"        text
) PARTITION BY RANGE ("дата_время_события");

CREATE TABLE public.ext_journal_prepared_2019 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');

CREATE TABLE public.ext_journal_prepared_2020 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');

CREATE TABLE public.ext_journal_prepared_2021 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');

CREATE TABLE public.ext_journal_prepared_2022 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');

CREATE TABLE public.ext_journal_prepared_2023 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE public.ext_journal_prepared_2024 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE public.ext_journal_prepared_2025 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE TABLE public.ext_journal_prepared_2026 PARTITION OF public.ext_journal_prepared
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
