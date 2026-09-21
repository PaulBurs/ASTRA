-- Поиск каналов по типу инженерной системы и датчика.

CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_astra_channels_system_type
ON astra_channels (
    engineering_system,
    sensor_type
);


-- Быстрый поиск всех каналов объекта.

CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_astra_channels_object
ON astra_channels (
    object_id
);
