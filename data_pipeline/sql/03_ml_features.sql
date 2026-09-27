-- =====================================================================
-- 03_ml_features.sql  (версия 2: окно нормировки зависит от типа датчика)
-- Перевод ml.dataset_events в числовую ML-таблицу ml.dataset_ml:
--   * категории -> коды по таблицам ml.map_* (коды совпадают с features_catalog.txt);
--   * значение_число -> очистка служебных кодов -> скользящая нормировка по каналу
--     z = (x - mean) / sqrt(var + eps) по окну [t - L, t) того же канала
--     (только прошлое, текущая секунда не входит) - та же формула, что на инференсе;
--   * время с прошлого события канала -> round(ln(1 + секунды), 6) -> та же нормировка.
--   Окно L по типу датчика (ml.window_params):
--      1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
--      7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
--     30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
--     90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
-- Коды категорий и флаги НЕ нормируются.
--
-- Предусловие: выполнены 01 и 02 (есть ml.ref_* и ml.dataset_events).
-- Запуск: psql -d djkh08 -f sql/03_ml_features.sql   (или DBeaver, Alt+X)
-- Каждый блок (год x группа типов) начинается с DELETE своих строк - его можно перезапустить отдельно.
-- Для окна берутся ещё и последние L дней предыдущего года - на стыке лет значения точные.
-- Если ml.dataset_ml уже собрана версией 1 (окно 24 ч для всех), быстрее запустить
-- 03b_update_windows.sql - он пересчитает только типы с окном 7/30/90 дней.
-- =====================================================================

SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';
-- JIT-компиляция на этих оконных запросах замедляет расчёт в десятки раз (проверено) - выключаем
SET jit = off;

-- 1. Таблицы кодов и параметров ---------------------------------------
DROP TABLE IF EXISTS ml.map_sensor_type, ml.map_value_type, ml.map_state,
                     ml.map_object, ml.map_complex, ml.map_channel, ml.norm_params CASCADE;

CREATE TABLE ml.map_sensor_type ("код" smallint PRIMARY KEY, "тип_датчика" text UNIQUE NOT NULL);
INSERT INTO ml.map_sensor_type VALUES
(1, '9-секционный люк'),
(2, 'Газовый датчик'),
(3, 'Датчик движения'),
(4, 'Датчик дыма'),
(5, 'Датчик затопления'),
(6, 'Датчик температуры'),
(7, 'ИБП'),
(8, 'КД АВ'),
(9, 'КД Дверь'),
(10, 'КД Люк'),
(11, 'Переключатель'),
(12, 'Ручной извещатель'),
(13, 'Состояние УИР-Р'),
(14, 'Состояние вентилятора'),
(15, 'Состояние насоса'),
(16, 'Состояние охраны'),
(17, 'Состояние фазы'),
(18, 'Стекло'),
(19, 'Тепловой датчик');

CREATE TABLE ml.map_value_type ("код" smallint PRIMARY KEY, "тип_значения" text UNIQUE NOT NULL);
INSERT INTO ml.map_value_type VALUES
(1, 'binary'),
(2, 'datetime'),
(3, 'numeric'),
(4, 'text');

-- код 0 = у события нет текстового состояния (числовое / binary / datetime)
CREATE TABLE ml.map_state ("код" smallint PRIMARY KEY, "название_состояния" text UNIQUE NOT NULL,
                           "техническое" smallint NOT NULL);
INSERT INTO ml.map_state VALUES
(0, '<нет состояния>', 0),
(1, 'Батарея неисправна', 0),
(2, 'Батарея разряжена', 0),
(3, 'В норме от +3 до +40', 0),
(4, 'Включен', 0),
(5, 'Вызов', 0),
(6, 'Выключен', 1),
(7, 'Движения нет', 0),
(8, 'Дыма нет', 0),
(9, 'Есть питание', 0),
(10, 'Затоплен', 0),
(11, 'Много неисправных устройств', 0),
(12, 'На охране', 0),
(13, 'Не замкнут', 0),
(14, 'Не определено', 1),
(15, 'Неисправен', 1),
(16, 'Неопределен', 1),
(17, 'Норма', 1),
(18, 'Обесточен', 0),
(19, 'Обнаружен газ', 0),
(20, 'Обнаружен дым', 0),
(21, 'Обнаружено движение', 0),
(22, 'Отключено устройство', 1),
(23, 'Питание от батарей', 0),
(24, 'Питание от сети', 0),
(25, 'Работают все насосы в АНС', 0),
(26, 'Разговор', 0),
(27, 'Рычаг норма', 0),
(28, 'Рычаг сдернут', 0),
(29, 'Снято с охраны', 0),
(30, 'Температура выше 40ºC', 0),
(31, 'Температура ниже 3ºC', 0),
(32, 'Устройства на объекте исправны', 0);

CREATE TABLE ml.map_complex ("код" smallint PRIMARY KEY, "ид_комплекса" bigint UNIQUE NOT NULL, "название" text);
INSERT INTO ml.map_complex VALUES
(1, 5, 'объект Альфа'),
(2, 6, 'объект Бета'),
(3, 7, 'объект Гамма'),
(4, 8, 'Комплекс объект Дельта'),
(5, 9, 'объект Вита'),
(6, 11, 'объект Эпсилон'),
(7, 12, 'объект Зита'),
(8, 15, 'объект Каппа'),
(9, 3218, 'объект Йота'),
(10, 3355, 'объект Тау'),
(11, 3359, 'объект Омикрон'),
(12, 3828, 'объект Мю'),
(13, 4068, 'объект Сигма'),
(14, 4356, 'ПС объект Ро'),
(15, 4573, 'ПС объект Омега'),
(16, 5327, 'объект Кси');

CREATE TABLE ml.map_object ("код" smallint PRIMARY KEY, "ид_объект" bigint UNIQUE NOT NULL, "вид_объекта" text, "название" text);
INSERT INTO ml.map_object VALUES
(1, 20, 'guardObject', 'объект Фита'),
(2, 28, 'guardObject', 'объект Вита'),
(3, 42, 'guardObject', 'объект Каппа ОС'),
(4, 99, 'controlHouse', 'ДП объект Вита'),
(5, 108, 'controlHouse', 'ДП ПС объект Ро'),
(6, 111, 'controlHouse', 'ДП объект Бета'),
(7, 165, 'guardObject', 'объект Бета'),
(8, 3215, 'guardObject', 'объект Йота'),
(9, 3216, 'controlHouse', 'ДП объект Йота'),
(10, 3250, 'controlHouse', 'Шкаф ОПС объект Йота'),
(11, 3356, 'guardObject', 'ПС объект Тау'),
(12, 3360, 'controlHouse', 'ДУ объект Омикрон'),
(13, 3388, 'controlHouse', 'ДУ объект Тау'),
(14, 3902, 'controlHouse', 'ДП объект Эпсилон'),
(15, 3903, 'controlHouse', 'Шкафы ОС объект Эпсилон'),
(16, 3904, 'guardObject', 'объект Эпсилон ОС'),
(17, 3905, 'guardObject', 'объект Пси ОС'),
(18, 4069, 'guardObject', 'объект Сигма'),
(19, 4095, 'guardObject', 'объект Хи'),
(20, 4177, 'controlHouse', 'ДП объект Сигма'),
(21, 4369, 'controlHouse', 'ДУ ПС объект Ро'),
(22, 4370, 'guardObject', 'объект Ро'),
(23, 4391, 'guardObject', 'объект Омикрон'),
(24, 4392, 'controlHouse', 'ДП объект Омикрон'),
(25, 4541, 'controlHouse', 'Шкаф ОПС объект Хи'),
(26, 4543, 'controlHouse', 'ДУ объект Хи'),
(27, 4569, 'controlHouse', 'Шкаф ОПС ПС объект Ро'),
(28, 4574, 'controlHouse', 'ДП ПС объект Омега'),
(29, 4577, 'controlHouse', 'Шкаф ОПС ПС объект Омега'),
(30, 4610, 'controlHouse', 'ДУ объект Дельта'),
(31, 4648, 'guardObject', 'ПС объект Омега'),
(32, 4763, 'controlHouse', 'Шкаф ОПС объект Омикрон'),
(33, 4765, 'controlHouse', 'Шкаф ОПС объект Бета'),
(34, 4767, 'controlHouse', 'Шкаф ОПС объект Вита'),
(35, 4768, 'controlHouse', 'Шкаф ОПС объект Сигма'),
(36, 4770, 'controlHouse', 'Шкаф ОПС объект Зита'),
(37, 5003, 'controlHouse', 'ДУ ПС объект Омега'),
(38, 5009, 'controlHouse', 'Шкаф ОПС ПС объект Тау'),
(39, 5011, 'controlHouse', 'ДУ объект Вита'),
(40, 5113, 'guardObject', 'объект Дельта'),
(41, 5114, 'controlHouse', 'Шкаф ОПС объект Дельта'),
(42, 5122, 'controlHouse', 'ДУ объект Альфа'),
(43, 5123, 'controlHouse', 'ДП объект Альфа'),
(44, 5124, 'controlHouse', 'ДП объект Альфа 2 этаж'),
(45, 5129, 'guardObject', 'объект Фита'),
(46, 5132, 'controlHouse', 'ДП объект Зита'),
(47, 5218, 'controlHouse', 'объект Йота ДУ'),
(48, 5332, 'guardObject', 'объект Кси ПК0-ПК202'),
(49, 5333, 'controlHouse', 'ДУ объект Кси'),
(50, 5336, 'controlHouse', 'ДП объект Кси'),
(51, 5338, 'controlHouse', 'Шкаф ОПС, ДУ объект Кси'),
(52, 5339, 'guardObject', 'объект Пси'),
(53, 5340, 'controlHouse', 'объект Пси шкаф ОПС'),
(54, 5343, 'guardObject', 'объект Кси ПК202-ПК302'),
(55, 5537, 'guardObject', 'объект Пси ПС'),
(56, 5539, 'guardObject', 'объект Эпсилон ПС'),
(57, 5540, 'controlHouse', 'Шкафы ПС объект Эпсилон'),
(58, 5567, 'guardObject', 'объект Каппа ПС'),
(59, 5574, 'controlHouse', 'объект Каппа шкафы'),
(60, 5578, 'controlHouse', 'объект Дзета ДУ'),
(61, 5579, 'controlHouse', 'объект Дзета шкафы'),
(62, 5580, 'guardObject', 'объект Дзета ОС'),
(63, 5581, 'guardObject', 'объект Дзета ПС'),
(64, 5582, 'guardObject', 'объект Зита ОС'),
(65, 5583, 'guardObject', 'объект Зита ПС'),
(66, 5591, 'controlHouse', 'объект Зита ДУ'),
(67, 5593, 'controlHouse', 'объект Зита шкафы'),
(68, 5594, 'controlHouse', 'объект Дзета щит. ПК48 Г1 ПК5'),
(69, 5657, 'controlHouse', 'объект Каппа ДУ'),
(70, 5674, 'controlHouse', 'объект Мю ДП'),
(71, 5675, 'controlHouse', 'объект Мю ДУ'),
(72, 5676, 'guardObject', 'объект Мю ОС'),
(73, 5677, 'guardObject', 'объект Мю ПС'),
(74, 5678, 'controlHouse', 'объект Мю шкафы'),
(75, 5961, 'guardObject', 'объект Гамма ОС'),
(76, 5962, 'guardObject', 'объект Гамма ПС'),
(77, 5963, 'controlHouse', 'объект Гамма ДУ'),
(78, 5966, 'controlHouse', 'объект Гамма шкафы');

-- Статические признаки канала (коды + пикет из названия датчика: «ПК546+2» -> 546)
CREATE TABLE ml.map_channel AS
SELECT c."ид_канала_данных"::int                                         AS "ид_канала_данных",
       st."код"                                                          AS "код_типа_датчика",
       mo."код"                                                          AS "код_объекта",
       mx."код"                                                          AS "код_комплекса",
       (o."вид_объекта" = 'guardObject')::int::smallint                  AS "объект_охранный",
       substring(c."название_датчика" from '[Пп][Кк]\s*([0-9]+)')::smallint AS "пикет"
FROM ml.ref_channels c
JOIN ml.ref_objects     o  ON o."ид_объект"    = c."ид_объект"
JOIN ml.map_sensor_type st ON st."тип_датчика" = c."тип_датчика"
JOIN ml.map_object      mo ON mo."ид_объект"   = c."ид_объект"
JOIN ml.map_complex     mx ON mx."ид_комплекса" = o."родитель";
ALTER TABLE ml.map_channel ADD PRIMARY KEY ("ид_канала_данных");

-- Параметры очистки и нормировки значения (по типу датчика).
-- Числовые значения у типов, которых здесь нет, считаются служебными.
CREATE TABLE ml.norm_params (
    "код_типа_датчика" smallint PRIMARY KEY,
    "мин"              numeric  NOT NULL,   -- допустимый диапазон [мин; макс]
    "макс"             numeric  NOT NULL,
    "служебные_коды"   numeric[] NOT NULL,  -- точные значения-коды ошибок
    "eps"              numeric  NOT NULL,   -- (шаг датчика)^2
    "комментарий"      text
);
INSERT INTO ml.norm_params VALUES
(2, -1, 100, ARRAY[2.55, 10.23, 327.68]::numeric[], 0.0001, '% объёма метана, шаг 0.01; 2.55/10.23/327.68 = 255/1023/32768 делённые на 100'),
(6, -50, 100, ARRAY[]::numeric[], 1.0, '°C, целые; -3276…-3255 и 950…999 - служебные'),
(7, 0, 100, ARRAY[]::numeric[], 1.0, 'целые 0…100');

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

-- 2. Итоговая таблица ------------------------------------------------
DROP TABLE IF EXISTS ml.dataset_ml CASCADE;
CREATE TABLE ml.dataset_ml (
    "дата_время_события"        timestamp NOT NULL,
    "ид_канала_данных"          int       NOT NULL,   -- ключ, не признак
    "код_типа_датчика"          smallint  NOT NULL,
    "код_объекта"               smallint  NOT NULL,
    "код_комплекса"             smallint  NOT NULL,
    "объект_охранный"           smallint  NOT NULL,
    "пикет"                     smallint,
    "код_типа_значения"         smallint  NOT NULL,
    "код_состояния"             smallint  NOT NULL,
    "состояние_техническое"     smallint  NOT NULL,
    "тревожное_событие"         smallint  NOT NULL,
    "тревожное_по_справочнику"  smallint  NOT NULL,
    "час"                       smallint  NOT NULL,   -- 0..23
    "день_недели"               smallint  NOT NULL,   -- 0 = пн … 6 = вс
    "месяц"                     smallint  NOT NULL,   -- 1..12
    "значение"                  real,                 -- очищенное число (NULL: нет числа или служебное)
    "служебное_значение"        smallint  NOT NULL,
    "значение_z"                real,                 -- скользящая нормировка значения
    "мало_истории_значение"     smallint  NOT NULL,
    "лог_dt"                    real,                 -- ln(1 + сек с прошлого события канала)
    "лог_dt_z"                  real,
    "мало_истории_dt"           smallint  NOT NULL
) PARTITION BY RANGE ("дата_время_события");
CREATE TABLE ml.dataset_ml_2019 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE ml.dataset_ml_2020 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE ml.dataset_ml_2021 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE ml.dataset_ml_2022 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE ml.dataset_ml_2023 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE ml.dataset_ml_2024 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE ml.dataset_ml_2025 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE ml.dataset_ml_2026 PARTITION OF ml.dataset_ml FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

-- ===== 2019 ============================================================

-- 3.1 Год 2019, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2019 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2019-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2020-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2019-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.2 Год 2019, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.3 Год 2019, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.4 Год 2019, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.5 Год 2020, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2020 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2020-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2021-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2020-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.6 Год 2020, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.7 Год 2020, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.8 Год 2020, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.9 Год 2021, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2021 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2021-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2022-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2021-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.10 Год 2021, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.11 Год 2021, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.12 Год 2021, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.13 Год 2022, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2022 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2022-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2023-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2022-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.14 Год 2022, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.15 Год 2022, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.16 Год 2022, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.17 Год 2023, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2023 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2023-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2024-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2023-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.18 Год 2023, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.19 Год 2023, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.20 Год 2023, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.21 Год 2024, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2024 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2024-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2025-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2024-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.22 Год 2024, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.23 Год 2024, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.24 Год 2024, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.25 Год 2025, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2025 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2025-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2026-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2025-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.26 Год 2025, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.27 Год 2025, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.28 Год 2025, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 3.29 Год 2026, окно 1 дн.: Газовый датчик, Датчик движения, Состояние УИР-Р
DELETE FROM ml.dataset_ml_2026 WHERE "код_типа_датчика" IN (2, 3, 13);

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
    WHERE e."тип_датчика" IN ('Газовый датчик', 'Датчик движения', 'Состояние УИР-Р')
      AND e."дата_время_события" >= TIMESTAMP '2026-01-01' - INTERVAL '1 days'
      AND e."дата_время_события" <  TIMESTAMP '2027-01-01'
),
-- последнее событие каждого канала ДО начала буфера (для точного dt на стыке лет)
lb AS MATERIALIZED (
    SELECT mc."ид_канала_данных" AS ch,
           (SELECT max(z."дата_время_события") FROM ml.dataset_events z
             WHERE z."ид_канала_данных" = mc."ид_канала_данных"
               AND z."дата_время_события" < TIMESTAMP '2026-01-01' - INTERVAL '1 days') AS t_before
    FROM ml.map_channel mc
    WHERE mc."код_типа_датчика" IN (2, 3, 13)
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
                 RANGE BETWEEN INTERVAL '1 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
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

-- 3.30 Год 2026, окно 7 дн.: КД Дверь, Переключатель, Состояние вентилятора, Состояние насоса, Состояние охраны, Состояние фазы
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

-- 3.31 Год 2026, окно 30 дн.: Датчик температуры, КД АВ, Стекло, Тепловой датчик
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

-- 3.32 Год 2026, окно 90 дн.: 9-секционный люк, Датчик дыма, Датчик затопления, ИБП, КД Люк, Ручной извещатель
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

-- 4. Индекс, статистика, представление --------------------------------
CREATE INDEX "ix_ml_канал_время" ON ml.dataset_ml ("ид_канала_данных", "дата_время_события");
ANALYZE ml.dataset_ml;

-- sin/cos не храним (экономия места), считаются на лету
CREATE OR REPLACE VIEW ml.v_dataset_ml AS
SELECT d.*,
       sin(2 * pi() * "час" / 24.0)::real          AS "час_sin",
       cos(2 * pi() * "час" / 24.0)::real          AS "час_cos",
       sin(2 * pi() * "день_недели" / 7.0)::real   AS "день_недели_sin",
       cos(2 * pi() * "день_недели" / 7.0)::real   AS "день_недели_cos",
       sin(2 * pi() * ("месяц" - 1) / 12.0)::real  AS "месяц_sin",
       cos(2 * pi() * ("месяц" - 1) / 12.0)::real  AS "месяц_cos"
FROM ml.dataset_ml d;

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
