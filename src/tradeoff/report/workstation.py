"""Offline view of recorded prices and paired decision traces (no model output)."""
from __future__ import annotations

import html
import math
from datetime import datetime, timezone
from typing import Any


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else '—'), quote=True)


def _finite(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _time(value: Any) -> str | None:
    try:
        instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return instant.astimezone(timezone.utc).isoformat() if instant.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _target(point: dict) -> str | None:
    value = point.get('target')
    return str(value) if _finite(value) else None


def recorded_data(report: dict) -> dict:
    """Align by actual instants; absent prices or paired values remain absent."""
    trace = (report.get('baseline') or {}).get('trace') or []
    witness = report.get('witness') or {}
    original = {_time(p.get('timestamp')): p for p in trace if _time(p.get('timestamp'))}
    paired = {_time(p.get('timestamp')): p for p in witness.get('mutated_trace', []) if _time(p.get('timestamp'))}
    tape = {_time(p.get('timestamp')): (i, p) for i, p in enumerate(witness.get('original_rows', [])) if _time(p.get('timestamp'))}
    changes = {p.get('index'): p for p in witness.get('changed_rows', [])}
    cutoff = _time(witness.get('cutoff'))
    decision = _time(witness.get('decision_timestamp'))
    bars = []
    # A failed or unstable callback supplies no stable trace to replay.
    for stamp in sorted(set(original) | set(tape)) if original else []:
        row_index, row = tape.get(stamp, (None, {}))
        change = changes.get(row_index, {}) if row_index is not None else {}
        before, after = change.get('before') or {}, change.get('after') or {}
        fields = [{'field': key, 'before': str(before.get(key, '—')), 'after': str(after.get(key, '—'))}
                  for key in dict.fromkeys([*before, *after]) if before.get(key) != after.get(key)]
        ohlc = {key: row[key] for key in ['open', 'high', 'low', 'close']} if all(_finite(row.get(key)) for key in ['open', 'high', 'low', 'close']) else None
        if ohlc and not (ohlc['low'] <= min(ohlc['open'], ohlc['close']) <= max(ohlc['open'], ohlc['close']) <= ohlc['high']):
            ohlc = None
        available = _time(change.get('available_at') or row.get('available_at'))
        bars.append({'timestamp': stamp, 'time_ms': datetime.fromisoformat(stamp).timestamp() * 1000, 'row_index': row_index,
                     'original_target': _target(original.get(stamp, {})),
                     'intervention_target': _target(paired.get(stamp, {})),
                     'ohlc': ohlc, 'ohlc_display': {key: str(value) for key, value in ohlc.items()} if ohlc else None, 'available_at': available,
                     'unavailable': available > cutoff if available and cutoff else None,
                     'changed': bool(change), 'changes': fields})
    decision_index = next((i for i, p in enumerate(bars) if p['timestamp'] == decision), None)
    cutoff_index = next((i for i, p in enumerate(bars) if p['timestamp'] == cutoff), None)
    changed_indices = [i for i, p in enumerate(bars) if p['changed']]
    anchors = [i for i in [decision_index, cutoff_index, *changed_indices] if i is not None]
    start, end = (max(0, min(anchors) - 12), min(len(bars) - 1, max(anchors) + 12)) if anchors else (0, len(bars) - 1)
    values = [p.get('target') for p in [*original.values(), *paired.values()] if _finite(p.get('target'))]
    exact_scale = all(not isinstance(value, int) or abs(value) <= 9007199254740991 for value in values)
    if values:
        try:
            exact_scale = exact_scale and math.isfinite(max(values) - min(values))
        except OverflowError:
            exact_scale = False
    price_values = [value for bar in bars if bar['ohlc'] for value in bar['ohlc'].values()]
    price_exact_scale = all(not isinstance(value, int) or abs(value) <= 9007199254740991 for value in price_values)
    if price_values:
        try:
            price_exact_scale = price_exact_scale and math.isfinite(max(price_values) - min(price_values))
        except OverflowError:
            price_exact_scale = False
    return {'bars': bars, 'price_exact_scale': price_exact_scale, 'decision_index': decision_index, 'cutoff': cutoff, 'cutoff_index': cutoff_index,
            'cutoff_ms': datetime.fromisoformat(cutoff).timestamp() * 1000 if cutoff else None,
            'changed_indices': changed_indices, 'initial_index': decision_index if decision_index is not None else 0,
            'focus_start': start, 'focus_end': end, 'has_prices': any(p['ohlc'] for p in bars),
            'exact_scale': exact_scale, 'units': 'Observed position units' if report.get('trace_kind') == 'observed_position' else 'Target units'}


def _bounds(values: list) -> tuple[float, float]:
    low, high = min(values), max(values)
    pad = max((high - low) * .09, max(abs(low), abs(high), 1) * .0005)
    lower, upper = low - pad, high + pad
    if not math.isfinite(lower):
        lower = low
    if not math.isfinite(upper):
        upper = high
    if not math.isfinite(upper - lower):
        lower, upper = low, high
    if lower == upper:
        lower = math.nextafter(lower, -math.inf)
    return lower, upper


def _label(value: float) -> str:
    return f'{value:,.2f}' if abs(value) < 100000 else f'{value:.3g}'


def chart_markup(model: dict) -> str:
    bars = model['bars']
    if not bars:
        return '<div class="trace-unavailable"><h3>Recorded decision trace unavailable</h3><p>Review the audit reason and declared search scope.</p></div>'
    first, last = model['focus_start'], model['focus_end']
    visible = bars[first:last + 1]
    width, height, left, right = 900, 480, 68, 20
    plot_width = width - left - right
    span = max(last - first, 1)
    time_start, time_end = bars[first]['time_ms'], bars[last]['time_ms']
    time_span = max(time_end - time_start, 1)
    time_x = lambda instant: left + (instant - time_start) / time_span * plot_width
    x = lambda index: time_x(bars[index]['time_ms'])
    chunks = []
    for top, bottom in [(45, 290), (340, 420)]:
        for n in range(4):
            y = top + (bottom - top) * n / 3
            chunks.append(f'<line x1="{left}" x2="{width-right}" y1="{y:.2f}" y2="{y:.2f}" class="chart-grid"/>')
    cutoff_index = model['cutoff_index']
    # Shade input records from their actual availability, including late publications.
    for index in range(first, last + 1):
        if bars[index]['unavailable'] is not True:
            continue
        start = left if index == first else (x(index - 1) + x(index)) / 2
        end = width - right if index == last else (x(index) + x(index + 1)) / 2
        chunks.append(f'<rect x="{start:.2f}" y="35" width="{end-start:.2f}" height="395" class="unavailable-region"/>')
    if any(bar['unavailable'] is True for bar in visible):
        chunks.append(f'<text x="{width-right-6}" y="32" text-anchor="end" class="chart-label">Shaded input: unavailable at cutoff</text>')
    chunks.append('<text x="68" y="23" class="chart-track-title">Original OHLC</text>')
    prices = [p['ohlc'][key] for p in visible if p['ohlc'] for key in ['low', 'high']] if model['price_exact_scale'] else []
    if prices:
        low, high = _bounds(prices)
        py = lambda value: 45 + 245 * ((high - value) / (high - low))
        for n in range(4):
            value = high - (high - low) * (n / 3)
            chunks.append(f'<text x="58" y="{45+245*n/3+4:.2f}" text-anchor="end" class="chart-label">{_label(value)}</text>')
        candle_width = min(8, plot_width / max(len(visible), 1) * .62)
        for index in range(first, last + 1):
            price = bars[index]['ohlc']
            if price is None:
                continue
            cx = x(index)
            top = min(py(price['open']), py(price['close']))
            body_height = max(.8, abs(py(price['open']) - py(price['close'])))
            tone = 'candle-up' if price['close'] >= price['open'] else 'candle-down'
            chunks.append(f'<line x1="{cx:.2f}" x2="{cx:.2f}" y1="{py(price["high"]):.2f}" y2="{py(price["low"]):.2f}" class="candle-wick {tone}"/><rect x="{cx-candle_width/2:.2f}" y="{top:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" class="candle-body {tone}"/>')
    else:
        message = 'Recorded OHLC scale unavailable · exact values in table' if model['has_prices'] else 'Recorded OHLC unavailable'
        chunks.append(f'<text x="68" y="170" class="chart-empty-label">{message}</text>')
    chunks.append(f'<text x="68" y="322" class="chart-track-title">{_escape(model["units"])} · step</text>')
    targets = [float(p[key]) for p in visible for key in ['original_target', 'intervention_target'] if p[key] is not None]
    if targets and model['exact_scale']:
        low, high = _bounds(targets)
        ty = lambda value: 340 + 80 * ((high - float(value)) / (high - low))
        for n in range(3):
            value = high - (high - low) * (n / 2)
            chunks.append(f'<text x="58" y="{340+80*n/2+4:.2f}" text-anchor="end" class="chart-label">{_label(value)}</text>')
        for key, css in [('original_target', 'position-original'), ('intervention_target', 'position-intervention')]:
            segments, running = [], False
            for index in range(first, last + 1):
                value = bars[index][key]
                if value is None:
                    running = False
                    continue
                segments.append(f'{"H" if running else "M"}{x(index):.2f}' + (f'V{ty(value):.2f}' if running else f',{ty(value):.2f}'))
                running = True
            if segments:
                chunks.append(f'<path d="{" ".join(segments)}" class="{css}"/>')
    elif targets:
        chunks.append('<text x="68" y="380" class="chart-empty-label">Exact values in inspector · scale unavailable</text>')
    for index, label, css, label_y in [(model['decision_index'], 'Decision', 'decision-marker', 58), *[(i, f'Changed row {bars[i]["row_index"]}', 'changed-marker', 106) for i in model['changed_indices']]]:
        if index is not None and first <= index <= last:
            cx = x(index)
            chunks.append(f'<line x1="{cx:.2f}" x2="{cx:.2f}" y1="35" y2="430" class="{css}"/><text x="{min(cx+6, width-125):.2f}" y="{label_y}" class="{css} marker-label">{_escape(label)}</text>')
    if model.get('cutoff_ms') is not None and time_start <= model['cutoff_ms'] <= time_end:
        cx = time_x(model['cutoff_ms'])
        chunks.append(f'<line x1="{cx:.2f}" x2="{cx:.2f}" y1="35" y2="430" class="cutoff-marker"/><text x="{min(cx+6, width-125):.2f}" y="82" class="cutoff-marker marker-label">Cutoff</text>')
    for index in sorted(set([first, first + span // 2, last])):
        stamp = bars[index]['timestamp']
        chunks.append(f'<text x="{x(index):.2f}" y="452" text-anchor="{"start" if index == first else "end" if index == last else "middle"}" class="chart-label">{_escape(stamp[5:10])} {stamp[11:16]}</text>')
    selection = x(model['initial_index'])
    chunks.append(f'<line id="trace-selection" x1="{selection:.2f}" x2="{selection:.2f}" y1="35" y2="430" class="trace-selection"/>')
    return f'<svg id="temporal-chart" class="temporal-chart" viewBox="0 0 {width} {height}" role="img" aria-labelledby="temporal-title temporal-desc" data-left="{left}" data-width="{plot_width}" data-start="{first}" data-end="{last}"><title id="temporal-title">Recorded prices and paired decisions</title><desc id="temporal-desc">Original recorded OHLC above, original and intervention decision steps below. The cutoff marks the availability boundary; exact availability and paired values are in the inspector and table. Time labels are UTC.</desc><g id="trace-plot">{"".join(chunks)}</g></svg>'


def _short_time(value: Any) -> str:
    stamp = _time(value)
    if not stamp:
        return 'Not recorded'
    instant = datetime.fromisoformat(stamp)
    return instant.strftime('%b %d · %H:%M UTC')


def _price_text(value: Any) -> str:
    if not _finite(value):
        return '—'
    return f'{value:.4g}' if abs(value) >= 10000000 else f'{value:,.4f}'.rstrip('0').rstrip('.')


def _ohlc(prices: dict | None) -> str:
    if not prices:
        return 'Not recorded'
    return ''.join(f'<span class="ohlc-item"><small>{label}</small><strong title="{_escape(prices[key])}">{_price_text(prices[key])}</strong></span>' for key, label in [('open', 'O'), ('high', 'H'), ('low', 'L'), ('close', 'C')])


def _facts(bar: dict, model: dict) -> str:
    values = [('Original position' if model['units'].startswith('Observed') else 'Original target', bar.get('original_target'), 'selected-original'),
              ('Intervened position' if model['units'].startswith('Observed') else 'Intervened target', bar.get('intervention_target'), 'selected-intervention'),
              ('Time · UTC', bar.get('timestamp'), 'selected-timestamp'),
              ('Cutoff · UTC', model.get('cutoff'), 'selected-cutoff'),
              ('Available · UTC', bar.get('available_at'), 'selected-available'),
              ('At cutoff', 'Unavailable' if bar.get('unavailable') else 'Available' if bar.get('unavailable') is False else 'Not recorded', 'selected-availability'),
              ('Changed row', bar.get('row_index') if bar.get('changed') else '—', 'selected-row')]
    markup = ''
    for label, value, identity in values:
        rendered = _short_time(value) if identity in ['selected-timestamp', 'selected-cutoff', 'selected-available'] else value
        markup += f'<div><dt>{_escape(label)}</dt><dd id="{identity}" title="{_escape(value)}">{_escape(rendered)}</dd></div>'
    return markup + f'<div><dt>Original OHLC</dt><dd id="selected-ohlc" class="ohlc-grid">{_ohlc(bar.get("ohlc"))}</dd></div>'


def render_workstation(report: dict) -> str:
    model = recorded_data(report)
    bars = model['bars']
    index = model['initial_index']
    bar = bars[index] if bars else {}
    disabled = '' if bars else ' disabled'
    range_disabled = '' if bars and (model['focus_start'] > 0 or model['focus_end'] < len(bars)-1) else ' disabled'
    range_label = 'Witness range' if report.get('witness') else 'Recorded range'
    witness_disabled = '' if model['decision_index'] is not None else ' disabled'
    changed_disabled = '' if model['changed_indices'] else ' disabled'
    rows = ''.join('<tr>' + ''.join(f'<td>{_escape(value)}</td>' for value in [i, p['timestamp'], p['original_target'], p['intervention_target'], p['available_at'], 'CHANGED' if p['changed'] else '—', ' / '.join(str(p['ohlc'][key]) for key in ['open', 'high', 'low', 'close']) if p['ohlc'] else 'Not recorded']) + '</tr>' for i, p in enumerate(bars))
    changes = ''.join(f'<div><span>{_escape(p["field"])}</span><strong>{_escape(p["before"])} → {_escape(p["after"])}</strong></div>' for p in bar.get('changes', [])) or '<p>No changed fields at this bar.</p>'
    copy = '<button type="button" class="button js-only" data-copy="test-command" data-copy-status="verification-copy-status">Copy verification command</button><p id="verification-copy-status" class="copy-status" role="status"></p>' if report.get('witness') and (report.get('artifacts') or {}).get('test') else '<a class="text-link" href="#method">Review scope</a>'
    return f'''<article id="temporal-analysis" class="audit-workstation"><header class="workstation-topline"><h2>Recorded evidence</h2><div class="chart-legend"><span><i class="legend-line original"></i>Original</span><span><i class="legend-line intervention"></i>Intervened</span><span>UTC · offline</span></div></header><div class="workstation-layout"><div class="workstation-stage"><div id="trace-plot-scroll" class="trace-plot-scroll" tabindex="0" role="region" aria-label="Recorded evidence chart; scroll horizontally">{chart_markup(model)}</div><div class="trace-controls js-only"><button type="button" id="trace-previous" class="icon-button" aria-label="Previous recorded bar"{disabled}>←</button><button type="button" id="trace-replay" class="button" aria-pressed="false"{disabled}>Play trace</button><input id="trace-scrubber" type="range" min="0" max="{max(len(bars)-1, 0)}" value="{index}" aria-label="Recorded evidence bar" aria-valuetext="Bar {index}: {_escape(bar.get('timestamp'))}"{disabled}><button type="button" id="trace-next" class="icon-button" aria-label="Next recorded bar"{disabled}>→</button><label class="range-label"><span class="sr-only">Chart range</span><select id="trace-range"{range_disabled}><option value="witness">{range_label}</option><option value="full">Full tape</option></select></label></div><p id="trace-cursor" class="trace-cursor">{f'Bar {index} / {len(bars)-1} · {_short_time(bar.get("timestamp"))}' if bars else 'No recorded trace to replay.'}</p></div><aside class="bar-inspector" aria-label="Selected evidence"><h3>Selected evidence</h3><dl id="bar-inspector-values" class="inspector-facts">{_facts(bar, model)}</dl><div id="bar-change-details" class="changed-field-list">{changes}</div><div class="inspector-actions"><button type="button" id="witness-select" class="button js-only"{witness_disabled}>Focus witness</button><button type="button" id="changed-row-select" class="button js-only"{changed_disabled}>Select changed row</button>{copy}</div></aside></div><details class="data-disclosure"><summary>Recorded evidence table · {len(bars)} bars <span aria-hidden="true">+</span></summary><div class="table-scroll" tabindex="0" role="region" aria-label="Recorded evidence table"><table id="trace-table"><caption>Zero-based bars. Recorded original prices; absent paired values are unavailable.</caption><thead><tr><th scope="col">Bar</th><th scope="col">Time · UTC</th><th scope="col">Original</th><th scope="col">Intervened</th><th scope="col">Available · UTC</th><th scope="col">Record</th><th scope="col">Original O / H / L / C</th></tr></thead><tbody>{rows}</tbody></table></div></details></article>'''
