SERIES = (
    ('total', 'Всего', '#d8bc72'),
    ('photo', 'Фото', '#79c7c0'),
    ('video', 'Видео', '#9caee8'),
    ('video_link', 'Ссылки', '#d99aa9'),
)


def build_line_chart(rows, width=900, height=260, padding=30):
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
    labels = [
        {'x': padding + index * usable_width / denominator, 'label': row['day'].strftime('%d.%m')}
        for index, row in enumerate(rows)
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
