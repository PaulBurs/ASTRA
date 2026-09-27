"""
improve.py - автоматическое улучшение модели на ваших данных (запускается у вас, одной командой).

Что делает (выбор ВЕЗДЕ только по valid; test смотрится один раз в самом конце):
  1. Сравнивает наборы признаков: v4 (периодичность и склонность датчика) / v5 (+динамика
     значений) / v6 (+регулярность эпизодов и «висящая» тревога) / v6 + ид объекта.
  2. Подбирает гиперпараметры LightGBM (Optuna, байесовский поиск).
  3. Пробует отдельные модели-«специалисты» для групп датчиков (газ, пожарные, охранные,
     инженерные) и оставляет те, что на valid лучше общей модели.
  4. Сохраняет лучшую конфигурацию в --out в том же формате, что model.py train,
     поэтому прогноз делается как обычно: python model.py predict --out <папка>.
  5. Печатает таблицу всех экспериментов и итог на test.

Запуск (из папки, где лежит sample_30.parquet):
    pip install optuna
    python djkh_model/improve.py --data sample_30.parquet --out out_best
Быстрый прогон для проверки:  --trials 5

Отдельная модель для газа на ВСЕХ газовых датчиках из полных файлов (в срезе их 20, всего 529):
    python djkh_model/improve.py --data "data/dataset_ml_202[2-6].csv.gz" --types 2 \
        --event-neg-frac 0.2 --out out_gas
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

GROUPS = {
    'газ':        [2],
    'пожарные':   [4, 12, 19],               # дым, ручной извещатель, тепловой
    'охранные':   [1, 3, 9, 10, 16, 18],     # люки, движение, двери, охрана, стекло
    'инженерные': [5, 6, 7, 8, 11, 13, 14, 15, 17],
}
MIN_GAIN = 0.02        # специалист оставляется, если лучше общей модели на valid хотя бы на 2%


class Journal:
    def __init__(self, path):
        self.path, self.rows = path, []

    def add(self, stage, name, va, extra=None):
        r = dict(этап=stage, вариант=name, pr_auc_valid=None if va is None else round(va, 4), **(extra or {}))
        self.rows.append(r)
        pd.DataFrame(self.rows).to_csv(self.path, index=False)
        M.log(f'[{stage}] {name}: PR-AUC valid = {va:.4f}' if va is not None else f'[{stage}] {name}: -')


def tune(ctx, cols, cats, n_trials, timeout_s, threads, journal):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = dict(
            learning_rate=trial.suggest_float('learning_rate', 0.02, 0.12, log=True),
            num_leaves=trial.suggest_int('num_leaves', 15, 255, log=True),
            min_child_samples=trial.suggest_int('min_child_samples', 50, 5000, log=True),
            feature_fraction=trial.suggest_float('feature_fraction', 0.3, 1.0),
            bagging_fraction=trial.suggest_float('bagging_fraction', 0.5, 1.0),
            lambda_l2=trial.suggest_float('lambda_l2', 1e-2, 100, log=True),
            min_gain_to_split=trial.suggest_float('min_gain_to_split', 0.0, 1.0),
            cat_smooth=trial.suggest_float('cat_smooth', 1, 100, log=True),
            max_depth=trial.suggest_categorical('max_depth', [-1, 6, 8, 12]),
        )
        mdl = M.train_lgb(ctx, cols, cats, params, threads=threads, rounds=3000)
        va = M.ap_on(ctx, _pred(mdl, ctx, cols), ctx['va'])
        trial.set_user_attr('iters', mdl.best_iteration)
        journal.add('подбор', f'trial {trial.number}', va, dict(деревьев=mdl.best_iteration,
                                                               параметры=json.dumps(params)))
        return va

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.enqueue_trial(dict(learning_rate=0.03, num_leaves=31, min_child_samples=1000, feature_fraction=0.6,
                             bagging_fraction=0.7, lambda_l2=10.0, min_gain_to_split=0.0, cat_smooth=50,
                             max_depth=-1))
    study.optimize(objective, n_trials=n_trials, timeout=timeout_s, gc_after_trial=True)
    return study.best_params, study.best_value


def _pred(mdl, ctx, cols):
    """Прогноз только на valid (остальное нули) - для быстрого подсчёта метрики."""
    p = np.zeros(len(ctx['meta']))
    va = ctx['va']
    p[va] = mdl.predict(ctx['X'].loc[va, cols], num_iteration=mdl.best_iteration)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--dicts', default=os.path.join(M.HERE, 'dicts'))
    ap.add_argument('--out', default='out_best')
    ap.add_argument('--trials', type=int, default=30, help='число попыток подбора гиперпараметров')
    ap.add_argument('--timeout-min', type=float, default=45, help='лимит времени на подбор, минут')
    ap.add_argument('--threads', type=int, default=os.cpu_count())
    ap.add_argument('--valid-start', default='2025-01-01')
    ap.add_argument('--test-start', default='2026-01-01')
    ap.add_argument('--channel-frac', type=float, default=1.0)
    ap.add_argument('--types', default=None, help='только эти коды типов, например 2 (газ)')
    ap.add_argument('--horizon', type=int, default=M.CFG['horizon_h'])
    ap.add_argument('--target-caught', type=float, default=None,
                    help='порог: поймать заранее эту долю эпизодов на valid (по умолчанию - максимум F1)')
    ap.add_argument('--event-neg-frac', type=float, default=1.0,
                    help='доля часов с событиями без тревоги впереди (для частых датчиков на полных данных: 0.1-0.3)')
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.out, exist_ok=True)
    journal = Journal(os.path.join(args.out, 'experiments.csv'))
    cfg = dict(M.CFG, extra_features=True, value_features=True, recurrence_features=True,
               horizon_h=args.horizon, target_caught=args.target_caught, channel_frac=args.channel_frac,
               types=M.parse_types(args.types), event_neg_keep_frac=args.event_neg_frac)
    files = M.resolve_files(args.data)
    M.log('файлы:', *files)
    ctx = M.prepare(files, cfg, args.dicts, args.valid_start, args.test_start)
    types = ctx['meta']['код_типа_датчика'].to_numpy()

    # подсказка по чистке цели
    st = ctx['states']
    sus = st[(st['доля_тревожных'] > 0.5) & (st['доля_в_типе'] > 0.15)]
    if len(sus):
        print('\nВНИМАНИЕ: «тревожные» состояния, занимающие большую долю событий типа '
              '(возможно, рабочий режим - см. exclude_alarm_states в model.py):')
        print(sus.to_string(index=False))

    # ---- 1. наборы признаков
    print('\n=== 1. Наборы признаков (параметры по умолчанию) ===')
    variants = {'v4: + периодичность и склонность': (True, False, False, False),
                'v5: v4 + динамика значений': (True, True, False, False),
                'v6: v5 + регулярность эпизодов': (True, True, True, False),
                'v6 + ид объекта': (True, True, True, True)}
    best = None
    for name, (extra, value, recur, obj) in variants.items():
        cols, cats = M.select_features(ctx['X'], obj, extra, value, recur)
        mdl = M.train_lgb(ctx, cols, cats, {}, threads=args.threads)
        va = M.ap_on(ctx, _pred(mdl, ctx, cols), ctx['va'])
        journal.add('признаки', name, va, dict(деревьев=mdl.best_iteration, признаков=len(cols)))
        if va is not None and (best is None or va > best[0]):
            best = (va, name, extra, value, recur, obj, cols, cats)
    va_feat, feat_name, extra, value, recur, obj, cols, cats = best
    M.log(f'лучший набор: {feat_name} ({va_feat:.4f})')

    # ---- 2. гиперпараметры
    print(f'\n=== 2. Подбор гиперпараметров: до {args.trials} попыток / {args.timeout_min:.0f} мин ===')
    try:
        best_params, va_tuned = tune(ctx, cols, cats, args.trials, args.timeout_min * 60, args.threads, journal)
    except ImportError:
        print('optuna не установлена (pip install optuna) - подбор пропущен')
        best_params, va_tuned = {}, -1
    if va_tuned <= va_feat:
        best_params, va_tuned = {}, va_feat
        M.log('подбор не улучшил результат - оставляю параметры по умолчанию')
    else:
        M.log(f'лучшие параметры: {best_params} ({va_tuned:.4f})')
    general = M.train_lgb(ctx, cols, cats, best_params, threads=args.threads)
    p_general = _pred(general, ctx, cols)

    # ---- 3. специалисты по группам
    print('\n=== 3. Отдельные модели для групп датчиков ===')
    specialists = []
    for g, gtypes in GROUPS.items():
        rows = np.isin(types, gtypes)
        m_va = ctx['va'] & rows
        if rows.all():
            M.log(f'{g}: в данных только эта группа - отдельная модель не нужна')
            continue
        if ctx['meta']['y'].to_numpy()[ctx['tr'] & rows].sum() < 50 or ctx['meta']['y'].to_numpy()[m_va].sum() < 20:
            M.log(f'{g}: мало тревог для отдельной модели - пропуск')
            continue
        va_gen = M.ap_on(ctx, p_general, m_va)
        journal.add('группы', f'{g}: общая модель', va_gen)
        best_g = None
        for use_obj in (False, True):
            c2, k2 = M.select_features(ctx['X'], use_obj, extra, value, recur)
            try:
                mdl = M.train_lgb(ctx, c2, k2, best_params, rows=rows, threads=args.threads)
            except Exception as e:  # noqa: BLE001
                M.log(f'{g}: ошибка обучения ({e}) - пропуск')
                continue
            p = np.zeros(len(types))
            p[m_va] = mdl.predict(ctx['X'].loc[m_va, c2], num_iteration=mdl.best_iteration)
            va_sp = M.ap_on(ctx, p, m_va)
            journal.add('группы', f'{g}: своя модель' + (' + ид объекта' if use_obj else ''), va_sp,
                        dict(деревьев=mdl.best_iteration))
            if best_g is None or va_sp > best_g[0]:
                best_g = (va_sp, mdl, c2, k2, use_obj)
        if best_g and va_gen is not None and best_g[0] > va_gen * (1 + MIN_GAIN):
            M.log(f'{g}: своя модель лучше ({best_g[0]:.4f} против {va_gen:.4f}) - берём')
            specialists.append(dict(name=g, types=gtypes, model=best_g[1], cols=best_g[2], cats=best_g[3]))
        else:
            M.log(f'{g}: общая модель не хуже - оставляем её')

    # ---- 4. финал: оценка на test один раз и сохранение
    print('\n=== 4. Итоговая модель (test смотрится впервые) ===')
    ctx['cfg'] = dict(cfg, object_id=obj, tuned_params=best_params)
    report, per_type = M.evaluate_and_save(
        ctx, general, cols, args.out, args.dicts, args.threads, specialists,
        extra_report=dict(feature_set=feat_name, tuned_params=best_params,
                          valid_default=va_feat, valid_tuned=va_tuned))

    print('\n' + '=' * 90)
    print('СВОДКА ЭКСПЕРИМЕНТОВ (PR-AUC на valid 2025; test не использовался для выбора)')
    print('=' * 90)
    j = pd.DataFrame(journal.rows)
    show = j[j['этап'] != 'подбор']
    print(show[['этап', 'вариант', 'pr_auc_valid']].to_string(index=False))
    tuned = j[j['этап'] == 'подбор']
    if len(tuned):
        print(f"подбор: {len(tuned)} попыток, лучший PR-AUC valid = {tuned['pr_auc_valid'].max():.4f}")
    print(f"\nВыбрано: {feat_name}; специалисты: {[s['name'] for s in specialists] or 'нет'}")
    te = report.get('test', {})
    if te:
        print(f"ИТОГ test: PR-AUC {te['model']['pr_auc']:.4f}  (база {te['baseline_alarm_24h']['pr_auc']:.4f} / "
              f"{te['baseline_since_episode']['pr_auc']:.4f}), precision {te['at_threshold']['precision']:.3f}, "
              f"recall {te['at_threshold']['recall']:.3f}, поймано эпизодов {te['episodes'].get('caught', 0):.3f}")
    print(f'Всё сохранено в {args.out}/ (прогноз: python djkh_model/model.py predict --data ... --out {args.out})')
    M.log(f'готово за {(time.time() - t0) / 60:.1f} мин')


if __name__ == '__main__':
    main()
