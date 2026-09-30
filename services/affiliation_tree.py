from database.queries import get_all_affiliations_flat


def build_affiliation_tree_flat_with_depth():
    """
    Список (id, name, depth) в порядке обхода дерева сверху вниз — удобно
    для кнопок с визуальным отступом по уровню вложенности.
    """
    all_rows = get_all_affiliations_flat()
    by_parent = {}
    for row in all_rows:
        by_parent.setdefault(row['parent_id'], []).append(row)

    result = []

    def walk(parent_id, depth):
        children = sorted(by_parent.get(parent_id, []), key=lambda r: r['name'])
        for child in children:
            result.append((child['id'], child['name'], depth))
            walk(child['id'], depth + 1)

    walk(None, 0)
    return result