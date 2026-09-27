"""lct_features - признаки для модели проекта 08.ДЖКХ.

Одно и то же преобразование «сырое событие СМВУ -> признаки» для обучения (ml.dataset_ml,
собирается SQL-скриптами из sql/) и для работы приложения (OnlineFeaturizer).
Только стандартная библиотека Python >= 3.9; для прогрева из БД нужен psycopg / psycopg2.
"""
from .featurizer import (ALL_COLUMNS, CYCLIC_COLUMNS, DATASET_COLUMNS, KEY_COLUMNS,
                         OnlineFeaturizer, featurize_stream)
from .parse import ParsedValue, parse_value
from .reference import Reference

__all__ = ['OnlineFeaturizer', 'featurize_stream', 'Reference', 'parse_value', 'ParsedValue',
           'DATASET_COLUMNS', 'CYCLIC_COLUMNS', 'ALL_COLUMNS', 'KEY_COLUMNS']
__version__ = '1.0.0'
