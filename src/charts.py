"""Charts drawn from tool results. The model names the data; the program reads every plotted value.

A chart spec points at one successful query and one list of records in its result, then names the
record fields to plot. Values are copied from those records, so a chart cannot contain a number the
tools did not return. Invalid specs are rejected with a reason; they never block the written answer.
"""
import math

TYPES = ('bar', 'hbar', 'line', 'scatter', 'pie')
SPEC_KEYS = {'type', 'title', 'query', 'records', 'label', 'x', 'y', 'sort', 'limit', 'diagonal'}
MAX_POINTS = {'bar': 30, 'hbar': 30, 'line': 60, 'scatter': 80, 'pie': 8}
MAX_SERIES = {'bar': 3, 'hbar': 3, 'line': 3, 'scatter': 1, 'pie': 1}
MAX_CHARTS = 6
_MISSING = object()


def _path(field, what):
    path = [field] if isinstance(field, str) else field
    if not isinstance(path, list) or not 1 <= len(path) <= 4 or not all(isinstance(k, str) or type(k) is int for k in path):
        raise ValueError(f'{what} must be a field name or a short path such as ["totals", 2]')
    return path


def _value(record, path):
    for key in path:
        if isinstance(record, dict) and isinstance(key, str) and key in record:
            record = record[key]
        elif isinstance(record, list) and type(key) is int and 0 <= key < len(record):
            record = record[key]
        else:
            return _MISSING
    return record


def _name(path, result):
    """Readable axis name; columnar metric arrays use the result's metric_columns."""
    columns = result.get('metric_columns')
    if len(path) == 2 and type(path[1]) is int and isinstance(columns, list) and path[1] < len(columns):
        return f'{columns[path[1]]} ({path[0]})'
    return '.'.join(str(k) for k in path)


def _number(value, what, label):
    if value is None or value is _MISSING:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{what} for {label!r} is not a number')
    return value


def resolve(spec, queries):
    """Turn a chart spec into plotted data read from queries; raises ValueError with the reason."""
    if not isinstance(spec, dict) or not set(spec) <= SPEC_KEYS or not {'type', 'title', 'query', 'records', 'y'} <= set(spec):
        raise ValueError('needs type, title, query, records and y (optional: label, x, sort, limit, diagonal)')
    kind = spec['type']
    if kind not in TYPES:
        raise ValueError('type must be one of ' + ', '.join(TYPES))
    if not isinstance(spec['title'], str) or not spec['title'].strip() or len(spec['title']) > 120:
        raise ValueError('title must be short text')
    # Several query_index values may be given for the pages of one lookup; their records are joined.
    ids = [spec['query']] if type(spec['query']) is int else spec['query']
    if not isinstance(ids, list) or not 1 <= len(ids) <= 5 or any(type(i) is not int or not 0 <= i < len(queries) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('query must be a query_index from this answer, or a list of up to 5 for pages of one lookup')
    if len({queries[i]['name'] for i in ids}) > 1:
        raise ValueError('all queries of one chart must be pages of the same tool lookup')
    path, records = _path(spec['records'], 'records'), []
    for i in ids:
        query = queries[i]
        if query['result'].get('error') or query['name'] == 'story_memory':
            raise ValueError(f'query {i} failed or is conversation memory, not archive data')
        found = _value(query['result'], path)
        if not isinstance(found, list) or not found or not all(isinstance(r, dict) for r in found):
            raise ValueError(f'records must point at a non-empty list of records in query {i}')
        records.extend(found)
    query, result = queries[ids[0]], queries[ids[0]]['result']
    # y is a list of fields (one per series); a single field name is accepted as shorthand.
    ys = [spec['y']] if isinstance(spec['y'], str) else spec['y']
    if not isinstance(ys, list) or not ys:
        raise ValueError('y must be a list of fields, e.g. ["goals"] or [["totals", 0]]')
    ys = [_path(y, 'y') for y in ys]
    if len(ys) > MAX_SERIES[kind]:
        raise ValueError(f'{kind} supports at most {MAX_SERIES[kind]} y field(s)')
    label = _path(spec['label'], 'label') if spec.get('label') is not None else None
    x = _path(spec['x'], 'x') if spec.get('x') is not None else None
    if kind in ('scatter', 'line') and x is None:
        raise ValueError(f'{kind} needs x')
    if kind != 'line' and label is None:
        raise ValueError(f'{kind} needs label')
    points, skipped = [], 0
    for record in records:
        name = _value(record, label) if label else None
        name = '' if name is _MISSING or name is None else str(name)
        values = [_number(_value(record, y), _name(y, result), name) for y in ys]
        if kind == 'scatter':
            xv = _number(_value(record, x), _name(x, result), name)
        elif kind == 'line':
            xv = _value(record, x)
            xv = None if xv is _MISSING else xv
            if xv is not None and type(xv) not in (str, int, float):
                raise ValueError('line x values must be dates, text or numbers')
        else:
            xv = None
        if any(v is None for v in values) or (kind in ('scatter', 'line') and xv is None):
            skipped += 1
            continue
        if kind == 'pie' and values[0] < 0:
            raise ValueError(f'pie values must not be negative ({name!r})')
        points.append(dict(label=name, x=xv, y=values))
    order = spec.get('sort', 'none' if kind in ('line', 'scatter') else 'desc')
    if order not in ('desc', 'asc', 'none'):
        raise ValueError('sort must be desc, asc or none')
    if kind == 'line':
        points.sort(key=lambda p: (str(type(p['x'])), p['x']))
    elif order != 'none':
        points.sort(key=lambda p: p['y'][0], reverse=order == 'desc')
    limit = spec.get('limit', MAX_POINTS[kind])
    if type(limit) is not int or not 1 <= limit <= MAX_POINTS[kind]:
        raise ValueError(f'limit must be 1-{MAX_POINTS[kind]} for {kind}')
    folded = None
    if kind == 'pie' and len(points) > limit:
        # Slices beyond the limit fold into one "Other" slice instead of a generated colour.
        rest = points[limit - 1:]
        folded = len(rest)
        points = points[:limit - 1] + [dict(label='Other', x=None, y=[sum(p['y'][0] for p in rest)], other=True)]
    elif len(points) > limit:
        if kind in ('scatter', 'line'):
            raise ValueError(f'{len(points)} points exceed the {kind} limit of {limit}')
        points = points[:limit]
    if len(points) < 2:
        raise ValueError('fewer than two plottable records')
    if kind == 'pie' and sum(p['y'][0] for p in points) <= 0:
        raise ValueError('pie values sum to zero')
    return dict(type=kind, title=spec['title'].strip(), x_label=_name(x, result) if x else None, y_labels=[_name(y, result) for y in ys],
                points=points, diagonal=bool(spec.get('diagonal')) and kind == 'scatter', skipped=skipped, folded=folded,
                source=dict(query=ids, tool=query['name'], snapshot_date=result.get('snapshot_date') or result.get('as_of')))
