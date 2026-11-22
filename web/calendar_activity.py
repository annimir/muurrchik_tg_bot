from services.tierlist_catalog import get_tierlist_character, get_tierlist_filter_options


def _date_range(start_date, end_date):
    if start_date == end_date:
        return start_date.strftime('%d.%m.%Y')
    if start_date.year == end_date.year:
        return f'{start_date.strftime("%d.%m")}–{end_date.strftime("%d.%m.%Y")}'
    return f'{start_date.strftime("%d.%m.%Y")}–{end_date.strftime("%d.%m.%Y")}'


def cycle_summary(cycle):
    details = cycle['details']
    code = cycle['activity_code']
    if code == 'onslaught':
        return 'Боссы: ' + ', '.join(details['bosses'])
    if code == 'theater':
        elements = {
            option['id']: option['name']
            for option in get_tierlist_filter_options(['genshin'])['element']
        }
        characters = [
            get_tierlist_character(character_id)
            for character_id in details['invited_characters']
        ]
        return 'Стихии: ' + ', '.join(elements.get(value, value) for value in details['elements']) + \
            '\nПриглашённые: ' + ', '.join(
                character['name'] if character else character_id
                for character, character_id in zip(characters, details['invited_characters'])
            )
    if code == 'abyss':
        return f"12-I: {details['first_half']}\n12-II: {details['second_half']}"
    return ''


def build_cycle_details(cycle):
    details = cycle['details']
    code = cycle['activity_code']
    sections = []
    if code == 'onslaught':
        sections.append({'title': 'Боссы', 'items': [
            {'name': name, 'description': f'Босс {index}'}
            for index, name in enumerate(details['bosses'], start=1)
        ]})
    elif code == 'theater':
        elements = {
            option['id']: option['name']
            for option in get_tierlist_filter_options(['genshin'])['element']
        }
        sections.append({'title': 'Стихии', 'items': [
            {'name': elements.get(value, value)} for value in details['elements']
        ]})
        characters = []
        for character_id in details['invited_characters']:
            character = get_tierlist_character(character_id)
            characters.append({
                'name': character['name'] if character else character_id,
                'image': character['image'] if character else None,
            })
        sections.append({'title': 'Приглашённые персонажи', 'items': characters})
    elif code == 'abyss':
        sections.append({'title': '12-й этаж', 'items': [
            {'name': 'Первая половина', 'description': details['first_half']},
            {'name': 'Вторая половина', 'description': details['second_half']},
        ]})
    return {
        'title': cycle['activity_name'], 'game_name': cycle['game_name'],
        'description': cycle['activity_description'],
        'date_label': _date_range(cycle['start_date'], cycle['end_date']),
        'sections': sections,
    }
