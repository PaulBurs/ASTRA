-- =====================================================================
-- 02_build_dataset.sql  (версия без процедур и $$-блоков, подходит для DBeaver)
-- Сборка единой очищенной таблицы ml.dataset_events:
--   журнал + справочник каналов + справочник объектов + исправленный справочник состояний.
--
-- Предусловия:
--   * журнал загружен в public.ext_journal_prepared (00_create_journal.sql + \copy CSV);
--   * выполнен 01_reference_tables.sql.
--
-- Запуск: из Terminal  psql -d djkh08 -f 02_build_dataset.sql
--         или в DBeaver: «Execute SQL Script» (Alt+X), НЕ Ctrl+Enter.
-- Каждый год - отдельный блок; при сбое можно перезапустить только его
-- (блок начинается с TRUNCATE своей партиции).
--
-- Удалено: столбцы тег_инженерной_системы, тип_инж_системы, ид_события,
--          значение_датчика_raw, значение_дата_время, иерархия_уровень, диспетчерское_название_объекта;
--          строки каналов-сирот; полные дубли (канал, время, тревожное_raw, значение_датчика_raw).
-- Добавлено: вид_объекта, ид_комплекса, тревожное_по_справочнику; тревожное_raw -> boolean.
-- 2021 год НЕ удаляется.
-- =====================================================================

SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';

-- 1. Целевая таблица -------------------------------------------------
DROP TABLE IF EXISTS ml.dataset_events CASCADE;

CREATE TABLE ml.dataset_events (
    "дата_время_события"        timestamp NOT NULL,
    "ид_канала_данных"          bigint    NOT NULL,
    "тип_датчика"               text      NOT NULL,
    "название_датчика"          text,
    "ид_объект"                 bigint    NOT NULL,
    "вид_объекта"               text,
    "ид_комплекса"              bigint,
    "тип_значения"              text      NOT NULL,
    "значение_число"            numeric,
    "значение_текст"            text,
    "тревожное_событие"         boolean   NOT NULL,
    "тревожное_по_справочнику"  boolean
) PARTITION BY RANGE ("дата_время_события");
CREATE TABLE ml.dataset_events_2019 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE ml.dataset_events_2020 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE ml.dataset_events_2021 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE ml.dataset_events_2022 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE ml.dataset_events_2023 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE ml.dataset_events_2024 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE ml.dataset_events_2025 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE ml.dataset_events_2026 PARTITION OF ml.dataset_events
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

DROP TABLE IF EXISTS ml.build_log;
CREATE TABLE ml.build_log (
    "год"                int PRIMARY KEY,
    "строк_в_источнике"  bigint,
    "строк_сирот"        bigint,
    "строк_загружено"    bigint,
    "удалено_дублей"     bigint
);

-- 2.1 Год 2019 ---------------------------------------------------
TRUNCATE ml.dataset_events_2019;
DELETE FROM ml.build_log WHERE "год" = 2019;

INSERT INTO ml.dataset_events_2019 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2019 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2019,
       (SELECT count(*) FROM public.ext_journal_prepared_2019),
       (SELECT count(*) FROM public.ext_journal_prepared_2019 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2019);

-- 2.2 Год 2020 ---------------------------------------------------
TRUNCATE ml.dataset_events_2020;
DELETE FROM ml.build_log WHERE "год" = 2020;

INSERT INTO ml.dataset_events_2020 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2020 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2020,
       (SELECT count(*) FROM public.ext_journal_prepared_2020),
       (SELECT count(*) FROM public.ext_journal_prepared_2020 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2020);

-- 2.3 Год 2021 ---------------------------------------------------
TRUNCATE ml.dataset_events_2021;
DELETE FROM ml.build_log WHERE "год" = 2021;

INSERT INTO ml.dataset_events_2021 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2021 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2021,
       (SELECT count(*) FROM public.ext_journal_prepared_2021),
       (SELECT count(*) FROM public.ext_journal_prepared_2021 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2021);

-- 2.4 Год 2022 ---------------------------------------------------
TRUNCATE ml.dataset_events_2022;
DELETE FROM ml.build_log WHERE "год" = 2022;

INSERT INTO ml.dataset_events_2022 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2022 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2022,
       (SELECT count(*) FROM public.ext_journal_prepared_2022),
       (SELECT count(*) FROM public.ext_journal_prepared_2022 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2022);

-- 2.5 Год 2023 ---------------------------------------------------
TRUNCATE ml.dataset_events_2023;
DELETE FROM ml.build_log WHERE "год" = 2023;

INSERT INTO ml.dataset_events_2023 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2023 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2023,
       (SELECT count(*) FROM public.ext_journal_prepared_2023),
       (SELECT count(*) FROM public.ext_journal_prepared_2023 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2023);

-- 2.6 Год 2024 ---------------------------------------------------
TRUNCATE ml.dataset_events_2024;
DELETE FROM ml.build_log WHERE "год" = 2024;

INSERT INTO ml.dataset_events_2024 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2024 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2024,
       (SELECT count(*) FROM public.ext_journal_prepared_2024),
       (SELECT count(*) FROM public.ext_journal_prepared_2024 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2024);

-- 2.7 Год 2025 ---------------------------------------------------
TRUNCATE ml.dataset_events_2025;
DELETE FROM ml.build_log WHERE "год" = 2025;

INSERT INTO ml.dataset_events_2025 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2025 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2025,
       (SELECT count(*) FROM public.ext_journal_prepared_2025),
       (SELECT count(*) FROM public.ext_journal_prepared_2025 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2025);

-- 2.8 Год 2026 ---------------------------------------------------
TRUNCATE ml.dataset_events_2026;
DELETE FROM ml.build_log WHERE "год" = 2026;

INSERT INTO ml.dataset_events_2026 (
    "дата_время_события", "ид_канала_данных", "тип_датчика", "название_датчика",
    "ид_объект", "вид_объекта", "ид_комплекса",
    "тип_значения", "значение_число", "значение_текст",
    "тревожное_событие", "тревожное_по_справочнику")
SELECT DISTINCT ON (j."ид_канала_данных", j."дата_время_события",
                    j."тревожное_raw", j."значение_датчика_raw")
       j."дата_время_события",
       j."ид_канала_данных",
       c."тип_датчика",
       c."название_датчика",
       c."ид_объект",
       o."вид_объекта",
       o."родитель",
       j."тип_значения",
       j."значение_число",
       j."значение_текст",
       (j."тревожное_raw" = 't'),
       s."тревожное"
FROM public.ext_journal_prepared_2026 j
JOIN ml.ref_channels c ON c."ид_канала_данных" = j."ид_канала_данных"
JOIN ml.ref_objects  o ON o."ид_объект"        = c."ид_объект"
LEFT JOIN ml.ref_state_fixed s
       ON j."тип_значения"       = 'text'
      AND s."тип_датчика"        = c."тип_датчика"
      AND s."название_состояния" = j."значение_текст"
ORDER BY j."ид_канала_данных", j."дата_время_события",
         j."тревожное_raw", j."значение_датчика_raw", j."ид_события";

INSERT INTO ml.build_log ("год", "строк_в_источнике", "строк_сирот", "строк_загружено")
SELECT 2026,
       (SELECT count(*) FROM public.ext_journal_prepared_2026),
       (SELECT count(*) FROM public.ext_journal_prepared_2026 j
         WHERE NOT EXISTS (SELECT 1 FROM ml.ref_channels c
                           WHERE c."ид_канала_данных" = j."ид_канала_данных")),
       (SELECT count(*) FROM ml.dataset_events_2026);

UPDATE ml.build_log
SET "удалено_дублей" = "строк_в_источнике" - "строк_сирот" - "строк_загружено";

-- 3. Индексы и статистика ---------------------------------------------
CREATE INDEX "ix_dataset_канал_время" ON ml.dataset_events ("ид_канала_данных", "дата_время_события");
CREATE INDEX "ix_dataset_тип_время"   ON ml.dataset_events ("тип_датчика", "дата_время_события");
ANALYZE ml.dataset_events;

-- 4. Контроль -------------------------------------------------------
-- 4.1 Баланс по годам: источник = сироты + загружено + дубли
SELECT * FROM ml.build_log ORDER BY "год";

-- 4.2 Итого (ожидается: источник 313 545 997, сирот 9 439 854, итог около 303,2 млн)
SELECT sum("строк_в_источнике") AS источник, sum("строк_сирот") AS сирот,
       sum("удалено_дублей") AS дублей, sum("строк_загружено") AS итог
FROM ml.build_log;

-- 4.3 Текстовые события без флага справочника (ожидается 0)
SELECT count(*) AS text_без_справочника
FROM ml.dataset_events
WHERE "тип_значения" = 'text' AND "тревожное_по_справочнику" IS NULL;
