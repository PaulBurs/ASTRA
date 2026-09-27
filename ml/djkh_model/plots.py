"""
plots.py - графики качества модели по папке, которую записал model.py train / improve.py.

    python djkh_model/plots.py --out out_v2            # PNG в out_v2/plots/

Что рисует (всё по test, кроме сравнения выборок):
  1_pr_curves.png          precision-recall: модель против двух базовых правил
  2_splits.png             PR-AUC на train / valid / test - видно переобучение
  3_by_type.png            PR-AUC по типам датчиков: модель против базы «тревоги за 24 ч»
  4_budget.png             доля пойманных эпизодов против числа предупреждений в сутки
  5_lead_time.png          за сколько часов до начала эпизода звучит первое предупреждение
  6_calibration.png        предсказанная вероятность против наблюдаемой доли тревог
  7_by_month.png           PR-AUC по месяцам test - стабильность во времени
  8_importance.png         топ-20 признаков по gain
Веса строк (прореживание пустых часов) учитываются везде.
"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# роли цветов (валидированная палитра: слоты 1-3 различимы и при дальтонизме)
SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3de'
SERIES = {'модель': '#2a78d6', 'база: тревоги за 24 ч': '#eb6834', 'база: давность эпизода': '#1baf7a'}
SCORE_COL = {'модель': 'score', 'база: тревоги за 24 ч': 'base_24h', 'база: давность эпизода': 'base_dt'}

HORIZON = 24          # горизонт прогноза, часов; берётся из metrics.json в main()

plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'font.family': 'DejaVu Sans', 'font.size': 10, 'text.color': INK,
    'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
    'axes.edgecolor': GRID, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8,
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.titleweight': 'bold',
    'axes.titlesize': 12, 'axes.axisbelow': True, 'axes.titlelocation': 'left', 'legend.frameon': False,
})


def wap(y, s, w):
    return average_precision_score(y, s, sample_weight=w) if 0 < y.sum() < len(y) else np.nan


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    print('  ', path)


def pr_curves(p, path):
    fig, ax = plt.subplots(figsize=(7, 5))
    y, w = p['y'].to_numpy(), p['w'].to_numpy()
    for name, col in SCORE_COL.items():
        pr, rc, _ = precision_recall_curve(y, p[col], sample_weight=w)
        ap = wap(y, p[col], w)
        ax.plot(rc, pr, color=SERIES[name], lw=2, label=f'{name}  (PR-AUC {ap:.3f})')
    ax.axhline(np.average(y, weights=w), color=INK2, lw=1, ls='--')
    ax.text(0.99, np.average(y, weights=w), 'случайное угадывание', ha='right', va='bottom', color=INK2, fontsize=8)
    ax.set(xlabel='recall (доля часов перед тревогой, которые модель отметила)',
           ylabel='precision', xlim=(0, 1), ylim=(0, 1))
    ax.set_title(f'Precision-recall на test, горизонт {HORIZON} ч')
    ax.legend(loc='upper right')
    save(fig, path)


def splits(report, path):
    names = [n for n in ('train', 'valid', 'test') if n in report]
    keys = {'модель': 'model', 'база: тревоги за 24 ч': 'baseline_alarm_24h',
            'база: давность эпизода': 'baseline_since_episode'}
    fig, ax = plt.subplots(figsize=(7, 4))
    bw = 0.26
    x = np.arange(len(names))
    for i, (lab, k) in enumerate(keys.items()):
        v = [report[n][k]['pr_auc'] or 0 for n in names]
        bars = ax.bar(x + (i - 1) * bw, v, bw - 0.02, color=SERIES[lab], label=lab)
        if lab == 'модель':
            for b, val in zip(bars, v):
                ax.text(b.get_x() + b.get_width() / 2, val, f'{val:.3f}', ha='center', va='bottom', fontsize=9)
    ax.set_xticks(x, names)
    ax.set_ylabel('PR-AUC')
    ax.set_title('PR-AUC по выборкам: разрыв train и valid/test = переобучение')
    ax.legend(loc='upper right')
    ax.grid(axis='x', visible=False)
    save(fig, path)


def by_type(p, names, path):
    rows = []
    for t, d in p.groupby('код_типа_датчика'):
        y, w = d['y'].to_numpy(), d['w'].to_numpy()
        if y.sum() == 0:
            continue
        rows.append((names.get(int(t), str(t)), wap(y, d['score'], w), wap(y, d['base_24h'], w),
                     np.average(y, weights=w), int(y.sum())))
    r = pd.DataFrame(rows, columns=['тип', 'модель', 'база', 'доля', 'полож']).sort_values('модель')
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(r) + 1.2))
    yy = np.arange(len(r))
    ax.barh(yy + 0.2, r['модель'], 0.38, color=SERIES['модель'], label='модель')
    ax.barh(yy - 0.2, r['база'], 0.38, color=SERIES['база: тревоги за 24 ч'], label='база: тревоги за 24 ч')
    for i, (m, n) in enumerate(zip(r['модель'], r['полож'])):
        ax.text(m + 0.005, i + 0.2, f'{m:.2f}', va='center', fontsize=8, color=INK)
    ax.set_yticks(yy, [f'{t}  ({n:,} полож.)'.replace(',', ' ') for t, n in zip(r['тип'], r['полож'])])
    ax.set_xlabel('PR-AUC на test')
    ax.set_title('Качество по типам датчиков')
    ax.legend(loc='lower right')
    ax.grid(axis='y', visible=False)
    save(fig, path)
    return r


def episodes(p):
    """Эпизоды test: макс. скор каждого правила за HORIZON ч до начала + давность прошлого эпизода."""
    e = p[np.isfinite(p['to_next']) & (p['to_next'] <= HORIZON)].copy()
    e['ep_h'] = ((e['ts'] - pd.Timestamp(0)) // pd.Timedelta(hours=1)) + e['to_next']
    agg = {c: 'max' for c in list(SCORE_COL.values()) + ['alert_margin'] if c in e}
    agg['h_since_start'] = 'max'
    return e, e.groupby(['ch', 'ep_h']).agg(agg)


def budget(p, path):
    """Сколько эпизодов поймано при заданном числе предупреждений на 100 датчиков в сутки."""
    _, ep = episodes(p)
    days = (p['ts'].max() - p['ts'].min()).total_seconds() / 86400 + 1 / 24
    n_ch = p['ch'].nunique()
    fig, ax = plt.subplots(figsize=(7, 5))
    for name, col in SCORE_COL.items():
        s, w = p[col].to_numpy(), p['w'].to_numpy()
        thr = np.unique(np.quantile(s, np.linspace(0.5, 0.9999, 300)))
        order = np.argsort(-s)
        cw = np.cumsum(w[order])
        # взвешенное число строк со скором >= порога
        n_alert = cw[np.searchsorted(-s[order], -thr, side='right') - 1]
        caught = (ep[col].to_numpy()[:, None] >= thr[None, :]).mean(0)
        ax.plot(n_alert / days / n_ch * 100, caught, color=SERIES[name], lw=2, label=name)
    ax.set_xscale('log')
    ax.set(xlabel='предупреждений (датчико-часов) в сутки на 100 датчиков, лог. шкала',
           ylabel='доля эпизодов, пойманных заранее', ylim=(0, 1))
    ax.set_title('Сколько тревог ловим при данной нагрузке на диспетчера')
    ax.legend(loc='upper left')
    save(fig, path)


def lead_time(p, thr_by_type, thr_general, path):
    e, ep = episodes(p)
    thr = e['код_типа_датчика'].map(thr_by_type).fillna(thr_general).to_numpy()
    e = e[e['score'].to_numpy() >= thr]
    lead = e.groupby(['ch', 'ep_h'])['to_next'].max()
    fig, ax = plt.subplots(figsize=(7, 4))
    step = 1 if HORIZON <= 48 else 6
    ax.hist(lead, bins=np.arange(0, HORIZON + step, step) + 0.5, color=SERIES['модель'], rwidth=0.9)
    ax.set(xlabel='часов до начала эпизода при первом предупреждении', ylabel='эпизодов')
    ax.set_title(f'Заблаговременность: поймано {len(lead)} из {len(ep)} эпизодов '
                 f'({len(lead) / max(len(ep), 1):.0%})')
    ax.grid(axis='x', visible=False)
    save(fig, path)


def calibration(p, path):
    q = pd.qcut(p['score'].rank(method='first'), 20, labels=False)
    d = p.assign(q=q, yw=p['y'] * p['w'], sw=p['score'] * p['w']).groupby('q')[['yw', 'sw', 'w']].sum()
    fig, ax = plt.subplots(figsize=(5.5, 5))
    lim = max(d['sw'].max() / d['w'].min(), 1e-3)
    ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls='--')
    ax.plot(d['sw'] / d['w'], d['yw'] / d['w'], color=SERIES['модель'], lw=2, marker='o', ms=5)
    ax.set(xlabel='средняя предсказанная вероятность (20 бинов)', ylabel='наблюдаемая доля тревог',
           xlim=(0, min(1, lim * 1.1)), ylim=(0, 1))
    ax.set_title('Калибровка на test')
    save(fig, path)


def by_month(p, path):
    m = p.assign(mon=p['ts'].dt.to_period('M'))
    fig, ax = plt.subplots(figsize=(7, 4))
    for name, col in SCORE_COL.items():
        v = m.groupby('mon').apply(lambda d: wap(d['y'].to_numpy(), d[col].to_numpy(), d['w'].to_numpy()),
                                   include_groups=False)
        ax.plot(v.index.astype(str), v.to_numpy(), color=SERIES[name], lw=2, marker='o', ms=6, label=name)
    ax.set(ylabel='PR-AUC', ylim=(0, None))
    ax.set_title('PR-AUC по месяцам test')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=3)
    save(fig, path)


def importance(out, path, top=20):
    imp = pd.read_csv(os.path.join(out, 'feature_importance.csv')).head(top)[::-1]
    fig, ax = plt.subplots(figsize=(7, 0.3 * top + 1))
    ax.barh(imp['признак'], imp['gain'] / imp['gain'].sum() * 100, color=SERIES['модель'], height=0.7)
    ax.set_xlabel('доля gain среди топ-20, %')
    ax.set_title(f'Топ-{top} признаков')
    ax.grid(axis='y', visible=False)
    save(fig, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='папка с результатами train')
    ap.add_argument('--dicts', default=os.path.join(HERE, 'dicts'))
    args = ap.parse_args()

    dst = os.path.join(args.out, 'plots')
    os.makedirs(dst, exist_ok=True)
    global HORIZON
    report = json.load(open(os.path.join(args.out, 'metrics.json'), encoding='utf-8'))
    HORIZON = int(report['config']['horizon_h'])
    p = pd.read_csv(os.path.join(args.out, 'predictions_test.csv.gz'), parse_dates=['ts'])
    if 'base_24h' not in p:
        raise SystemExit('predictions_test.csv.gz от старой версии model.py - переобучите модель')
    names = pd.read_csv(os.path.join(args.dicts, 'map_sensor_type.csv')).set_index('код')['тип_датчика'].to_dict()
    thr_by_type = {t: sp['threshold'] for sp in report.get('specialists', []) for t in sp['types']}
    thr_by_type.update({int(t): v for t, v in report.get('type_thresholds', {}).items()})

    pr_curves(p, os.path.join(dst, '1_pr_curves.png'))
    splits(report, os.path.join(dst, '2_splits.png'))
    by_type(p, names, os.path.join(dst, '3_by_type.png'))
    budget(p, os.path.join(dst, '4_budget.png'))
    lead_time(p, thr_by_type, report['threshold'], os.path.join(dst, '5_lead_time.png'))
    calibration(p, os.path.join(dst, '6_calibration.png'))
    by_month(p, os.path.join(dst, '7_by_month.png'))
    importance(args.out, os.path.join(dst, '8_importance.png'))

    # разбор эпизодов: «холодные» (у датчика не было эпизодов 30 дней) почти непредсказуемы
    thr = p['код_типа_датчика'].map(thr_by_type).fillna(report['threshold'])
    _, ep = episodes(p.assign(alert_margin=p['score'] - thr))
    ep = ep.assign(поймано=ep['alert_margin'] >= 0,
                   тип=np.where(ep['h_since_start'] > 720, 'холодный (не было эпизода 30 дн.)',
                                'был эпизод за 30 дн.'))
    print(f'\nЭпизоды test: {len(ep)}')
    print(ep.groupby('тип')['поймано'].agg(эпизодов='size', поймано='mean').to_string())


if __name__ == '__main__':
    main()
