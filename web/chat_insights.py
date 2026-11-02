import argparse
import json
import math
import random
import re
from collections import Counter
from functools import lru_cache
from itertools import combinations
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parent / 'content' / 'chat_insights.json'
TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
STOP_WORDS = frozenset('''
а алло ах без благодаря более больше будем будет будете будешь буду будут будучи бы была были было
быть в вам вами вас весь во вовсе вон вот все всего всех всю всё всём всё равно вы где да даже для
до его ей ему если есть ещё еще её ее ж же за здесь и из или им ими их к как какая какие каких какого
какой каком какую когда кого кому конечно которая которые который которых кроме кто куда ли либо лишь
мне мной много может можно мой моя моё мои моего моей моему мою мы на над надо наш наша наше наши
нашего нашей нашему нашу не него неё нее ней нему нею ни нибудь никогда никто ничего ничто но ну о
об оба один одна одни одного одной одному одну он она они оно от очень по под после при про раз разве
с сам сама сами само самого самой самом самому свою свои своих своего своей своему себе себя сейчас
со так такая такие таких такого такое такой таком такую там тебе тебя тем теми то того тоже той только
том тому тот ту ты у уже хотя чего чей чем чему через что чтобы чуть эта эти этим этими этих этого этой
этом этому этот эту я
and are but for from have has her hers him his how its our ours out she that the their theirs them they
this too was were what when where which who why with you your yours
амп блин вообще вроде давай давайте дело думать думаю думаешь если честно короче кстати ладно наверное
насчет нормально ок окей пон понял понятно просто реально сейчас сек секунду спасибо тип типа хорошо
хоть щас ща
была будь будто ведь вместо вне внутри вперед впереди всегда везде вниз внизу вокруг вперёд вчера
завтра сегодня теперь потом сначала затем иногда часто редко почти особенно именно например впрочем
однако поэтому потому тогда здесь туда сюда оттуда отсюда нигде никуда нисколько столько сколько
более менее очень слишком прям прямо капец жесть жестко хз имхо кек лол рофл ага угу неа ахах ахаха
хах хаха хахаха хахахаха ахахах ахахаха ха хахахахаха лмао
http https www com ru org net html jpg jpeg png mp4 telegram телеграм телеграмм
message photo video file files sticker stickers голосовое видеосообщение фото фотка фотку фотки
есть будут делать делаю делаешь делает сделать сделал сделала сделали сказать сказал сказала сказали
говорит говорю говорят говорить знаю знает знаете знаешь знать хотел хотела хотели хочет хочешь хочу
пошел пошла пошли идти иду идет идёт идете идёте работает работать работаю работают понимать понимаю
понимаешь казаться кажется казалось получается получилось получиться поставить взять взял взяла дать дал
дала дали надо нужно нужен нужна нужны можем могут могу могла могли сможет сможешь смогу
это меня мною нам нами нас них нет нету тут всем был пока почему зачем лучше что-то чем-то время день
точно опять помню сразу два двух двум двумя три трех трем тремя лет год года целом правда буквально
скорее из-за норм ваще чисто блять бля блядь каждый каждая каждые каждого каждому другой другая другие
других другого другому значит стоит чтоб как-то какой-то самое самый типо деле ним немного мало ради
дальше зато ибо обычно второй второго второму первый первого первому новый нового новому момент сильно
поняла поняли времени дня дней дню пиздец нахуй сука хуйня
'''.split())
CLOUD_LIMIT = 64
MAP_NODE_LIMIT = 48
MAP_EDGE_LIMIT = 110
CANDIDATE_LIMIT = 120


def extract_text(message):
    value = message.get('text', '')
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(
            part if isinstance(part, str) else str(part.get('text', ''))
            for part in value
        )
    return ''


def tokenize(text):
    cleaned = re.sub(r'https?://\S+|www\.\S+|(?<!\w)@\w+', ' ', text)
    tokens = []
    for match in TOKEN_RE.finditer(cleaned.casefold().replace('ё', 'е')):
        token = match.group().strip("-'")
        if 3 <= len(token) <= 32 and token not in STOP_WORDS:
            tokens.append(token)
    return tokens


def _new_period():
    return {
        'messages': 0, 'words': 0, 'authors': set(), 'first_date': None, 'last_date': None,
        'frequencies': Counter(), 'document_frequency': Counter(),
    }


def _message_year(message):
    date = message.get('date', '')
    return date[:4] if len(date) >= 4 and date[:4].isdigit() else None


def _update_period(period, message, tokens):
    date = message.get('date', '')
    period['messages'] += 1
    period['words'] += len(tokens)
    if message.get('from'):
        period['authors'].add(message['from'])
    if date:
        period['first_date'] = min(period['first_date'] or date, date)
        period['last_date'] = max(period['last_date'] or date, date)
    period['frequencies'].update(tokens)
    period['document_frequency'].update(set(tokens))


def _collect_statistics(messages):
    periods = {'all': _new_period()}
    for message in messages:
        if message.get('type') != 'message':
            continue
        text = extract_text(message)
        if not text.strip():
            continue
        year = _message_year(message)
        if not year:
            continue
        periods.setdefault(year, _new_period())
        tokens = tokenize(text)
        _update_period(periods['all'], message, tokens)
        _update_period(periods[year], message, tokens)
    return periods


def _ranked_words(period):
    frequencies = period['frequencies']
    return sorted(
        period['document_frequency'],
        key=lambda word: (-period['document_frequency'][word], -frequencies[word], word),
    )


def _collect_cooccurrences(messages, candidates):
    cooccurrences = {period: Counter() for period in candidates}
    for message in messages:
        if message.get('type') != 'message':
            continue
        year = _message_year(message)
        if not year:
            continue
        tokens = set(tokenize(extract_text(message)))
        for period in ('all', year):
            if period not in candidates:
                continue
            selected = sorted(tokens & candidates[period])
            cooccurrences[period].update(combinations(selected, 2))
    return cooccurrences


def _cloud(words, period):
    if not words:
        return []
    frequencies = period['document_frequency']
    maximum = frequencies[words[0]]
    placed = []
    rectangles = []
    for index, word in enumerate(words[:CLOUD_LIMIT]):
        count = frequencies[word]
        size = round(14 + 36 * math.sqrt(count / maximum), 1)
        width = len(word) * size * 0.62 + 12
        height = size * 1.35
        position = None
        for step in range(3600):
            angle = step * 0.23 + index * 0.7
            radius = step * 0.12
            x = 500 + math.cos(angle) * radius * 1.5
            y = 260 + math.sin(angle) * radius * 0.82
            rectangle = (x - width / 2, y - height / 2, x + width / 2, y + height / 2)
            if rectangle[0] < 12 or rectangle[2] > 988 or rectangle[1] < 14 or rectangle[3] > 506:
                continue
            if any(
                not (rectangle[2] + 5 < other[0] or rectangle[0] - 5 > other[2]
                     or rectangle[3] + 3 < other[1] or rectangle[1] - 3 > other[3])
                for other in rectangles
            ):
                continue
            position = (x, y)
            rectangles.append(rectangle)
            break
        if position:
            placed.append({
                'text': word, 'count': count, 'x': round(position[0], 2), 'y': round(position[1], 2),
                'size': size, 'tone': index % 5,
            })
    return placed


def _graph_edges(words, period, cooccurrences):
    selected = set(words)
    document_frequency = period['document_frequency']
    minimum_count = 3 if period['messages'] >= 100 else 1
    edges = []
    for (source, target), count in cooccurrences.items():
        if source not in selected or target not in selected or count < minimum_count:
            continue
        score = count / math.sqrt(document_frequency[source] * document_frequency[target])
        edges.append({
            'source': source, 'target': target, 'count': count,
            'score': score, 'strength': round(score, 4),
        })
    return sorted(
        edges,
        key=lambda edge: (-edge['score'], -edge['count'], edge['source'], edge['target']),
    )


def _connected_edges(edges, node_count):
    parent = {}

    def find(word):
        parent.setdefault(word, word)
        while parent[word] != word:
            parent[word] = parent[parent[word]]
            word = parent[word]
        return word

    selected = []
    selected_pairs = set()
    for edge in edges:
        source_root = find(edge['source'])
        target_root = find(edge['target'])
        if source_root == target_root:
            continue
        parent[source_root] = target_root
        selected.append(edge)
        selected_pairs.add((edge['source'], edge['target']))
    for edge in edges:
        if len(selected) >= min(MAP_EDGE_LIMIT, node_count * 2):
            break
        pair = (edge['source'], edge['target'])
        if pair not in selected_pairs:
            selected.append(edge)
            selected_pairs.add(pair)
    return selected[:min(MAP_EDGE_LIMIT, node_count * 2)]


def _communities(words, edges):
    labels = {word: index for index, word in enumerate(words)}
    adjacency = {word: [] for word in words}
    for edge in edges:
        adjacency[edge['source']].append((edge['target'], edge['score']))
        adjacency[edge['target']].append((edge['source'], edge['score']))
    randomizer = random.Random(41)
    order = list(words)
    for _ in range(30):
        randomizer.shuffle(order)
        changed = False
        totals = Counter(labels.values())
        for word in order:
            weights = Counter()
            for neighbor, weight in adjacency[word]:
                weights[labels[neighbor]] += weight
            if not weights:
                continue
            old_label = labels[word]
            new_label = max(weights, key=lambda label: (weights[label], totals[label], -label))
            if new_label != old_label:
                totals[old_label] -= 1
                totals[new_label] += 1
                labels[word] = new_label
                changed = True
        if not changed:
            break
    remap = {label: index for index, label in enumerate(sorted(set(labels.values())))}
    return {word: remap[label] for word, label in labels.items()}


def _layout(words, edges, communities, period):
    randomizer = random.Random(73)
    groups = sorted(set(communities.values()))
    centers = {}
    for index, group in enumerate(groups):
        angle = 2 * math.pi * index / max(len(groups), 1)
        centers[group] = (500 + 210 * math.cos(angle), 310 + 155 * math.sin(angle))
    positions = {}
    for word in words:
        center_x, center_y = centers[communities[word]]
        positions[word] = [center_x + randomizer.uniform(-85, 85), center_y + randomizer.uniform(-70, 70)]
    adjacency = {word: [] for word in words}
    for edge in edges:
        adjacency[edge['source']].append(edge)
        adjacency[edge['target']].append(edge)
    for iteration in range(320):
        forces = {word: [0.0, 0.0] for word in words}
        for index, source in enumerate(words):
            for target in words[index + 1:]:
                dx = positions[source][0] - positions[target][0]
                dy = positions[source][1] - positions[target][1]
                distance_squared = dx * dx + dy * dy
                if distance_squared < 1:
                    dx, dy, distance_squared = 0.1, 0.1, 0.02
                distance = math.sqrt(distance_squared)
                force = 2600 / (distance_squared + 100)
                fx, fy = dx / distance * force, dy / distance * force
                forces[source][0] += fx
                forces[source][1] += fy
                forces[target][0] -= fx
                forces[target][1] -= fy
        for edge in edges:
            source, target = edge['source'], edge['target']
            dx = positions[target][0] - positions[source][0]
            dy = positions[target][1] - positions[source][1]
            distance = max(math.hypot(dx, dy), 0.1)
            desired = 145 - edge['score'] * 55
            force = (distance - desired) * 0.0025 * (0.5 + edge['score'])
            fx, fy = dx / distance * force, dy / distance * force
            forces[source][0] += fx
            forces[source][1] += fy
            forces[target][0] -= fx
            forces[target][1] -= fy
        temperature = 22 * (1 - iteration / 320) + 1
        for word in words:
            forces[word][0] += (500 - positions[word][0]) * 0.0012
            forces[word][1] += (310 - positions[word][1]) * 0.0012
            length = max(math.hypot(*forces[word]), 0.001)
            step = min(length, temperature)
            positions[word][0] += forces[word][0] / length * step
            positions[word][1] += forces[word][1] / length * step
    min_x = min(position[0] for position in positions.values())
    max_x = max(position[0] for position in positions.values())
    min_y = min(position[1] for position in positions.values())
    max_y = max(position[1] for position in positions.values())
    for word in words:
        positions[word][0] = 75 + (positions[word][0] - min_x) / max(max_x - min_x, 1) * 850
        positions[word][1] = 65 + (positions[word][1] - min_y) / max(max_y - min_y, 1) * 490
    return positions


def _map(words, period, cooccurrences):
    if not words:
        return {'nodes': [], 'edges': [], 'communities': []}
    document_frequency = period['document_frequency']
    maximum = document_frequency[words[0]]
    edges = _connected_edges(_graph_edges(words, period, cooccurrences), len(words))
    communities = _communities(words, edges)
    positions = _layout(words, edges, communities, period)
    adjacency = {word: [] for word in words}
    for edge in edges:
        adjacency[edge['source']].append((edge['target'], edge['count'], edge['score']))
        adjacency[edge['target']].append((edge['source'], edge['count'], edge['score']))
    nodes = []
    for word in words:
        related = sorted(adjacency[word], key=lambda item: (-item[2], -item[1], item[0]))[:6]
        nodes.append({
            'word': word, 'count': document_frequency[word],
            'x': round(positions[word][0], 2), 'y': round(positions[word][1], 2),
            'radius': round(5 + 12 * math.sqrt(document_frequency[word] / maximum), 2),
            'font_size': round(12 + 7 * math.sqrt(document_frequency[word] / maximum), 1),
            'community': communities[word],
            'related': [
                {'word': neighbor, 'count': count, 'score': round(score, 4)}
                for neighbor, count, score in related
            ],
        })
    community_words = {}
    for word in words:
        community_words.setdefault(communities[word], []).append(word)
    community_data = [
        {
            'id': group,
            'label': ' · '.join(sorted(group_words, key=lambda word: words.index(word))[:3]),
        }
        for group, group_words in sorted(community_words.items())
    ]
    return {'nodes': nodes, 'edges': edges, 'communities': community_data}


def _display_date(value):
    return f'{value[8:10]}.{value[5:7]}.{value[:4]}' if value else ''


def _build_period(period, cooccurrences):
    ranked = _ranked_words(period)
    map_words = ranked[:MAP_NODE_LIMIT]
    return {
        'messages': period['messages'], 'words': period['words'], 'authors': len(period['authors']),
        'first_date': period['first_date'], 'last_date': period['last_date'],
        'date_range': (
            f'{_display_date(period["first_date"])} — {_display_date(period["last_date"])}'
            if period['first_date'] else 'Нет сообщений'
        ),
        'cloud': _cloud(ranked, period),
        'map': _map(map_words, period, cooccurrences),
    }


def _analyze(message_factory, source_name):
    statistics = _collect_statistics(message_factory())
    candidates = {
        key: set(_ranked_words(period)[:CANDIDATE_LIMIT])
        for key, period in statistics.items()
    }
    cooccurrences = _collect_cooccurrences(message_factory(), candidates)
    periods = {
        key: _build_period(period, cooccurrences[key])
        for key, period in statistics.items()
    }
    return {
        'version': 1,
        'source_name': source_name,
        'years': sorted(key for key in statistics if key != 'all'),
        'periods': periods,
    }


def build_chat_insights(messages, source_name='История чата'):
    messages = list(messages)
    return _analyze(lambda: iter(messages), source_name)


def generate_chat_insights(source_path, output_path=CONTENT_PATH):
    source_path = Path(source_path)

    def messages():
        with source_path.open(encoding='utf-8') as file:
            data = json.load(file)
        return iter(data['messages'])

    with source_path.open(encoding='utf-8') as file:
        source_name = json.load(file).get('name', 'История чата')
    insights = _analyze(messages, source_name)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as file:
        json.dump(insights, file, ensure_ascii=False, separators=(',', ':'))
    return insights


@lru_cache(maxsize=1)
def _load_insights():
    with CONTENT_PATH.open(encoding='utf-8') as file:
        return json.load(file)


def get_chat_insights(period='all'):
    data = _load_insights()
    if period not in data['periods']:
        return None
    return {
        'source_name': data['source_name'], 'years': data['years'],
        'selected_period': period, 'insights': data['periods'][period],
    }


def main():
    parser = argparse.ArgumentParser(description='Расчёт облака слов и семантической карты чата')
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=CONTENT_PATH)
    args = parser.parse_args()
    insights = generate_chat_insights(args.source, args.output)
    print(f'Сохранено: {args.output} ({len(insights["periods"])} периодов)')


if __name__ == '__main__':
    main()
