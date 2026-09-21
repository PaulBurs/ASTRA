-- ASTRA
-- Основная предметная схема PostgreSQL.
--
-- Объект -> Канал -> Событие


-- ============================================================
-- 1. ОБЪЕКТЫ
-- ============================================================

CREATE TABLE IF NOT EXISTS astra_objects (
    object_id BIGINT PRIMARY KEY,

    parent_id BIGINT NULL,

    hierarchy_level INTEGER NULL,

    object_type TEXT NULL,

    display_name TEXT NULL
);


-- ============================================================
-- 2. КАНАЛЫ / ДАТЧИКИ
-- ============================================================

CREATE TABLE IF NOT EXISTS astra_channels (
    sensor_id BIGINT PRIMARY KEY,

    engineering_system TEXT NOT NULL,

    sensor_type TEXT NOT NULL,

    engineering_system_tag TEXT NULL,

    sensor_name TEXT NULL,

    object_id BIGINT NOT NULL,

    CONSTRAINT fk_astra_channels_object
        FOREIGN KEY (object_id)
        REFERENCES astra_objects(object_id)
);


-- ============================================================
-- 3. ЖУРНАЛ СОБЫТИЙ
-- ============================================================

CREATE TABLE IF NOT EXISTS ext_journal_prepared (
    event_id BIGINT PRIMARY KEY,

    sensor_id BIGINT NOT NULL,

    alarm_raw TEXT NULL,

    sensor_value_raw TEXT NULL,

    occurred_at TIMESTAMP NOT NULL,

    value_type TEXT NOT NULL,

    numeric_value NUMERIC NULL,

    datetime_value TIMESTAMP NULL,

    text_value TEXT NULL
);


ALTER TABLE ext_journal_prepared
    DROP CONSTRAINT IF EXISTS chk_event_value_type;

ALTER TABLE ext_journal_prepared
    ADD CONSTRAINT chk_event_value_type
    CHECK (
        value_type IN (
            'numeric',
            'binary',
            'datetime',
            'text'
        )
    );
