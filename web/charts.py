SERIES = (
    ('total', 'Всего', '#d8bc72'),
    ('photo', 'Фото', '#79c7c0'),
    ('video', 'Видео', '#9caee8'),
    ('video_link', 'Ссылки', '#d99aa9'),
)


def build_line_chart(rows, width=900, height=260, padding=30, label_format='%d.%m'):
    maximum = max((row['total'] for row in rows), default=1) or 1
    usable_width = width - padding * 2
    usable_height = height - padding * 2
    denominator = max(len(rows) - 1, 1)
    series = []
    for key, label, color in SERIES:
        points = []
        for index, row in enumerate(rows):
            x = padding + index * usable_width / denominator
            y = height - padding - row[key] * usable_height / maximum
            points.append(f'{x:.1f},{y:.1f}')
        series.append({'key': key, 'label': label, 'color': color, 'points': ' '.join(points)})
    label_step = max((len(rows) + 11) // 12, 1)
    labels = [
        {'x': padding + index * usable_width / denominator, 'label': row['day'].strftime(label_format)}
        for index, row in enumerate(rows)
        if index % label_step == 0 or index == len(rows) - 1
    ]
    return {
        'width': width, 'height': height, 'padding': padding,
        'maximum': maximum, 'series': series, 'labels': labels,
    }


def build_daily_bars(analytics):
    maximum = max(analytics['total'], 1)
    return [
        {'key': key, 'label': label, 'color': color,
         'value': analytics[key], 'percent': analytics[key] * 100 / maximum}
        for key, label, color in SERIES
    ]


PIE_COLORS = (
    '#d8bc72', '#79c7c0', '#9caee8', '#d99aa9', '#a8d5a2',
    '#c5a3e0', '#e5ad7a', '#78b7d9', '#b8c2cf',
)


def build_pie_chart(rows, limit=8):
    visible_rows = list(rows[:limit])
    remaining = sum(row['cnt'] for row in rows[limit:])
    if remaining:
        visible_rows.append({'id': None, 'name': 'Остальные', 'cnt': remaining})
    total = sum(row['cnt'] for row in visible_rows)
    segments = []
    offset = 0
    for index, row in enumerate(visible_rows):
        percent = row['cnt'] * 100 / total if total else 0
        segments.append({
            'id': row['id'], 'name': row['name'], 'cnt': row['cnt'],
            'color': PIE_COLORS[index % len(PIE_COLORS)], 'percent': percent,
            'percent_label': f'{percent:.1f}'.replace('.', ','),
            'dash_offset': 25 - offset,
        })
        offset += percent
    return {'total': total, 'segments': segments}
