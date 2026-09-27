-- =====================================================================
-- 03b_update_windows.sql
-- Для УЖЕ СОБРАННОЙ ml.dataset_ml (версия 1, окно 24 ч для всех типов):
-- пересчитывает значение_z / лог_dt_z и флаги мало_истории для типов с окном 7, 30 и 90 дней.
-- Газ, датчики движения и УИР-Р (окно 1 день, как и было) не трогаются.
--   Окна по типам:
--      1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
--      7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
--     30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
--     90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
-- Результат идентичен полной сборке 03_ml_features.sql (версия 2).
-- Запуск: psql -d djkh08 -f sql/03b_update_windows.sql
-- =====================================================================

SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';
-- JIT-компиляция на этих оконных запросах замедляет расчёт в десятки раз (проверено) - выключаем
SET jit = off;

-- Окно скользящей нормировки по типу датчика (дни).
-- Минимальное из {1, 7, 30, 90}, при котором у >= 90% событий типа в окне >= 5 прошлых точек.
DROP TABLE IF EXISTS ml.window_params;
CREATE TABLE ml.window_params (
    "код_типа_датчика" smallint PRIMARY KEY,
    "окно_дней"        smallint NOT NULL
);
INSERT INTO ml.window_params VALUES
(1, 90),
(2, 1),
(3, 1),
(4, 90),
(5, 90),
(6, 30),
(7, 90),
(8, 30),
(9, 7),
(10, 90),
(11, 7),
(12, 90),
(13, 1),
(14, 7),
(15, 7),
(16, 7),
(17, 7),
(18, 30),
(19, 30);

-- ===== 2019 ============================================================

-- 3.1 Год 2019, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2019 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2019
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2019-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2020-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2019-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2019-01-01';

-- 3.2 Год 2019, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2019 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2019
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2019-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2020-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2019-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2019-01-01';

-- 3.3 Год 2019, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2019 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2019
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2019-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2020-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2019-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2019-01-01';

-- ===== 2020 ============================================================

-- 3.4 Год 2020, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2020 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2020
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2020-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2021-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2020-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2020-01-01';

-- 3.5 Год 2020, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2020 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2020
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2020-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2021-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2020-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2020-01-01';

-- 3.6 Год 2020, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2020 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2020
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2020-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2021-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2020-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2020-01-01';

-- ===== 2021 ============================================================

-- 3.7 Год 2021, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2021 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2021
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2021-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2022-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2021-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2021-01-01';

-- 3.8 Год 2021, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2021 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2021
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2021-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2022-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2021-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2021-01-01';

-- 3.9 Год 2021, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2021 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2021
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2021-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2022-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2021-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2021-01-01';

-- ===== 2022 ============================================================

-- 3.10 Год 2022, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2022 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2022
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2022-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2023-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2022-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2022-01-01';

-- 3.11 Год 2022, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2022 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2022
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2022-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2023-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2022-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2022-01-01';

-- 3.12 Год 2022, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2022 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2022
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2022-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2023-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2022-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2022-01-01';

-- ===== 2023 ============================================================

-- 3.13 Год 2023, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2023 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2023
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2023-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2024-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2023-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2023-01-01';

-- 3.14 Год 2023, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2023 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2023
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2023-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2024-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2023-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2023-01-01';

-- 3.15 Год 2023, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2023 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2023
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2023-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2024-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2023-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2023-01-01';

-- ===== 2024 ============================================================

-- 3.16 Год 2024, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2024 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2024
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2024-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2025-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2024-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2024-01-01';

-- 3.17 Год 2024, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2024 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2024
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2024-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2025-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2024-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2024-01-01';

-- 3.18 Год 2024, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2024 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2024
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2024-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2025-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2024-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2024-01-01';

-- ===== 2025 ============================================================

-- 3.19 Год 2025, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2025 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2025
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2025-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2026-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2025-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2025-01-01';

-- 3.20 Год 2025, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2025 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2025
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2025-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2026-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2025-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2025-01-01';

-- 3.21 Год 2025, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2025 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2025
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2025-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2026-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2025-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2025-01-01';

-- ===== 2026 ============================================================

-- 3.22 Год 2026, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
DELETE FROM ml.dataset_ml_2026 WHERE "код_типа_датчика" IN (9, 11, 14, 15, 16, 17);

INSERT INTO ml.dataset_ml_2026
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('КД Дверь', 'Переключатель', 'Состояние вентилятора', 'Состояние насоса', 'Состояние охраны', 'Состояние фазы')
      AND e."дата_время_события" >= TIMESTAMP '2026-01-01' - INTERVAL '7 days'
      AND e."дата_время_события" <  TIMESTAMP '2027-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2026-01-01' - INTERVAL '7 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (9, 11, 14, 15, 16, 17)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2026-01-01';

-- 3.23 Год 2026, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
DELETE FROM ml.dataset_ml_2026 WHERE "код_типа_датчика" IN (6, 8, 18, 19);

INSERT INTO ml.dataset_ml_2026
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('Датчик температуры', 'КД АВ', 'Стекло', 'Тепловой датчик')
      AND e."дата_время_события" >= TIMESTAMP '2026-01-01' - INTERVAL '30 days'
      AND e."дата_время_события" <  TIMESTAMP '2027-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2026-01-01' - INTERVAL '30 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (6, 8, 18, 19)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2026-01-01';

-- 3.24 Год 2026, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
DELETE FROM ml.dataset_ml_2026 WHERE "код_типа_датчика" IN (1, 4, 5, 7, 10, 12);

INSERT INTO ml.dataset_ml_2026
WITH src AS (
    SELECT e."дата_время_события" AS t,
           e."ид_канала_данных"   AS ch,
           e."тип_значения", e."значение_число" AS x, e."значение_текст",
           e."тревожное_событие", e."тревожное_по_справочнику",
           mc."код_типа_датчика", mc."код_объекта", mc."код_комплекса", mc."объект_охранный", mc."пикет",
           p."мин", p."макс", p."служебные_коды", p."eps"
    FROM ml.dataset_events e
    JOIN ml.map_channel mc     ON mc."ид_канала_данных" = e."ид_канала_данных"
    LEFT JOIN ml.norm_params p ON p."код_типа_датчика"  = mc."код_типа_датчика"
    WHERE e."тип_датчика" IN ('9-секционный люк', 'Датчик дыма', 'Датчик затопления', 'ИБП', 'КД Люк', 'Ручной извещатель')
      AND e."дата_время_события" >= TIMESTAMP '2026-01-01' - INTERVAL '90 days'
      AND e."дата_время_события" <  TIMESTAMP '2027-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2026-01-01' - INTERVAL '90 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (1, 4, 5, 7, 10, 12)
),
a AS (
    SELECT src.*,
           CASE WHEN "тип_значения" = 'numeric' AND x IS NOT NULL AND "eps" IS NOT NULL
                     AND x BETWEEN "мин" AND "макс" AND NOT (x = ANY("служебные_коды"))
                THEN x::numeric(14,4) END AS v,
           max(t) OVER (PARTITION BY ch ORDER BY t
                        RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING) AS t_prev
    FROM src
),
b AS (
    SELECT a.*,
           round(ln(1 + extract(epoch FROM a.t - COALESCE(a.t_prev, lb.t_before))::float8)::numeric, 6) AS log_dt
    FROM a
    JOIN lb ON lb.ch = a.ch
),
c AS (
    SELECT b.*,
           avg(v)            OVER w AS mu_v,
           var_pop(v)        OVER w AS var_v,
           count(v)          OVER w AS n_v,
           avg(log_dt)       OVER w AS mu_d,
           var_pop(log_dt)   OVER w AS var_d,
           count(log_dt)     OVER w AS n_d
    FROM b
    WINDOW w AS (PARTITION BY ch ORDER BY t
                 RANGE BETWEEN INTERVAL '90 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
)
SELECT c.t,
       c.ch::int,
       c."код_типа_датчика", c."код_объекта", c."код_комплекса", c."объект_охранный", c."пикет",
       vt."код",
       COALESCE(ms."код", 0),
       COALESCE(ms."техническое", 0),
       c."тревожное_событие"::int,
       COALESCE(c."тревожное_по_справочнику", false)::int,
       extract(hour FROM c.t)::int,
       (extract(isodow FROM c.t) - 1)::int,
       extract(month FROM c.t)::int,
       c.v::real,
       (c."тип_значения" = 'numeric' AND c.v IS NULL)::int,
       CASE WHEN c.v IS NOT NULL AND c.n_v >= 5
            THEN ((c.v - c.mu_v) / sqrt(c.var_v + c."eps"))::real END,
       (c.v IS NOT NULL AND c.n_v < 5)::int,
       c.log_dt::real,
       CASE WHEN c.log_dt IS NOT NULL AND c.n_d >= 5
            THEN ((c.log_dt - c.mu_d) / sqrt(c.var_d + 0.01))::real END,
       (c.log_dt IS NOT NULL AND c.n_d < 5)::int
FROM c
JOIN ml.map_value_type vt ON vt."тип_значения" = c."тип_значения"
LEFT JOIN ml.map_state ms ON ms."название_состояния" = c."значение_текст"
WHERE c.t >= TIMESTAMP '2026-01-01';

-- 4. Уборка удалённых строк и статистика --------------------------------
VACUUM ANALYZE ml.dataset_ml;

-- 5. Контроль -------------------------------------------------------
-- 5.1 Строк столько же, сколько в ml.dataset_events (ожидается 303 163 533 в обеих)
SELECT (SELECT count(*) FROM ml.dataset_events) AS событий,
       (SELECT count(*) FROM ml.dataset_ml)     AS ml_строк;

-- 5.2 По типам датчиков: окно, доля посчитанных z по значению и по dt
SELECT t."тип_датчика",
       w."окно_дней"                                                   AS окно,
       count(*)                                                        AS строк,
       count(d."значение")                                             AS с_числом,
       sum(d."служебное_значение")                                     AS служебных,
       round(100.0 * count(d."значение_z") / nullif(count(d."значение"), 0), 1) AS "z_знач_%",
       round(avg(d."значение_z")::numeric, 3)                          AS z_среднее,
       round(stddev_pop(d."значение_z")::numeric, 3)                   AS z_std,
       round(100.0 * count(d."лог_dt_z") / nullif(count(d."лог_dt"), 0), 1)     AS "z_dt_%"
FROM ml.dataset_ml d
JOIN ml.map_sensor_type t ON t."код" = d."код_типа_датчика"
JOIN ml.window_params   w ON w."код_типа_датчика" = d."код_типа_датчика"
GROUP BY 1, 2 ORDER BY 3 DESC;

-- 5.3 Размер итоговой таблицы
SELECT pg_size_pretty(sum(pg_total_relation_size(inhrelid))) AS размер
FROM pg_inherits WHERE inhparent = 'ml.dataset_ml'::regclass;
