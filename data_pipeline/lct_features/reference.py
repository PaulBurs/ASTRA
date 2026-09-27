"""Справочники и параметры - выгрузка таблиц ml.map_*, ml.norm_params, ml.window_params,
ml.ref_state_fixed из БД (лежат в lct_features/dicts/*.csv). Коды совпадают с ml.dataset_ml
и с features_catalog.txt. Если справочники в БД поменяются - перевыгрузите CSV
(tools/export_dicts.sh), код менять не нужно."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DICTS = Path(__file__).with_name('dicts')


def _read(name):
    with open(DICTS / f'{name}.csv', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class Channel:
    channel_id: int
    sensor_code: int
    sensor_type: str
    object_code: int
    complex_code: int
    guard_object: int
    picket: Optional[int]


@dataclass(frozen=True)
class NormParams:
    min: float
    max: float
    service: frozenset
    eps: float


class Reference:
    def __init__(self):
        self.sensor_type = {int(r['код']): r['тип_датчика'] for r in _read('map_sensor_type')}
        self.value_type_code = {r['тип_значения']: int(r['код']) for r in _read('map_value_type')}
        self.state = {r['название_состояния']: (int(r['код']), int(r['техническое']))
                      for r in _read('map_state')}
        self.channels = {}
        for r in _read('map_channel'):
            c = int(r['код_типа_датчика'])
            self.channels[int(r['ид_канала_данных'])] = Channel(
                int(r['ид_канала_данных']), c, self.sensor_type[c], int(r['код_объекта']),
                int(r['код_комплекса']), int(r['объект_охранный']),
                int(r['пикет']) if r['пикет'] else None)
        self.norm = {}
        for r in _read('norm_params'):
            svc = r['служебные_коды'].strip('{}')
            self.norm[int(r['код_типа_датчика'])] = NormParams(
                float(r['мин']), float(r['макс']),
                frozenset(float(x) for x in svc.split(',') if x), float(r['eps']))
        self.window_days = {int(r['код_типа_датчика']): int(r['окно_дней']) for r in _read('window_params')}
        self.state_alarm = {(r['тип_датчика'], r['название_состояния']): r['тревожное'] == 't'
                            for r in _read('state_alarm')}
