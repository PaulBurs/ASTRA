-- ASTRA
-- Минимальные данные только для локальной разработки.
--
-- Не являются реальными данными организаторов.

BEGIN;


-- ============================================================
-- ОБЪЕКТ
-- ============================================================

INSERT INTO astra_objects (
    object_id,
    parent_id,
    hierarchy_level,
    object_type,
    display_name
)
VALUES (
    1001,
    NULL,
    3,
    'collector',
    'ASTRA test object'
)
ON CONFLICT (object_id) DO NOTHING;


-- ============================================================
-- ГАЗОВЫЕ КАНАЛЫ
-- ============================================================

INSERT INTO astra_channels (
    sensor_id,
    engineering_system,
    sensor_type,
    engineering_system_tag,
    sensor_name,
    object_id
)
VALUES
(
    900001,
    'Газовая охрана',
    'Газовый датчик',
    'TEST-GAS-1',
    'Тестовый газовый датчик 1',
    1001
),
(
    900002,
    'Газовая охрана',
    'Газовый датчик',
    'TEST-GAS-2',
    'Тестовый газовый датчик 2',
    1001
)
ON CONFLICT (sensor_id) DO NOTHING;


-- ============================================================
-- СОБЫТИЯ
-- ============================================================

INSERT INTO ext_journal_prepared (
    event_id,
    sensor_id,
    alarm_raw,
    sensor_value_raw,
    occurred_at,
    value_type,
    numeric_value,
    datetime_value,
    text_value
)
VALUES
(
    9000001,
    900001,
    NULL,
    '0.01',
    '2026-03-05 08:00:00',
    'numeric',
    0.01,
    NULL,
    NULL
),
(
    9000002,
    900001,
    NULL,
    '0.03',
    '2026-03-05 08:10:00',
    'numeric',
    0.03,
    NULL,
    NULL
),
(
    9000003,
    900001,
    NULL,
    'Обнаружен газ',
    '2026-03-05 08:20:00',
    'text',
    NULL,
    NULL,
    'Обнаружен газ'
)
ON CONFLICT (event_id) DO NOTHING;


COMMIT;
