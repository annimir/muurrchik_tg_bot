import unittest

from web.chat_insights import build_chat_insights, extract_text, tokenize


def message(message_id, date, text, author='player'):
    return {
        'id': message_id, 'type': 'message', 'date': date,
        'from': author, 'from_id': f'user-{author}', 'text': text,
    }


class ChatInsightsTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            message(1, '2024-01-01T10:00:00', 'Райден и Фурина обсуждают крутки'),
            message(2, '2024-01-02T10:00:00', 'Райден и Фурина пьют чай', 'second'),
            message(3, '2024-01-03T10:00:00', 'Крутки для Райден, чай для Фурины'),
            message(4, '2024-01-04T10:00:00', 'https://example.com @someone это и нет'),
            message(5, '2025-02-01T10:00:00', 'Банбу встречает Алису'),
            message(6, '2025-02-02T10:00:00', [
                'Банбу и ', {'type': 'text_link', 'text': 'Алиса'}, ' идут в ЗЗЗ',
            ]),
            {'id': 7, 'type': 'service', 'date': '2025-02-03T10:00:00', 'text': 'Сервисное слово'},
        ]
        self.data = build_chat_insights(self.messages, 'Тестовый чат')

    def test_text_extraction_and_tokenization(self):
        self.assertEqual(extract_text(self.messages[5]), 'Банбу и Алиса идут в ЗЗЗ')
        self.assertEqual(
            tokenize('Ёлка, это @someone и https://example.com для Райден'),
            ['елка', 'райден'],
        )

    def test_periods_and_document_frequencies(self):
        all_period = self.data['periods']['all']
        year = self.data['periods']['2024']

        self.assertEqual(self.data['years'], ['2024', '2025'])
        self.assertEqual(all_period['messages'], 6)
        self.assertEqual(all_period['authors'], 2)
        self.assertEqual(year['messages'], 4)
        self.assertEqual(year['date_range'], '01.01.2024 — 04.01.2024')
        cloud_counts = {word['text']: word['count'] for word in year['cloud']}
        self.assertEqual(cloud_counts['райден'], 3)
        self.assertEqual(cloud_counts['фурина'], 2)
        self.assertEqual(cloud_counts['фурины'], 1)
        self.assertNotIn('someone', cloud_counts)
        self.assertNotIn('это', cloud_counts)

    def test_graph_layout_is_deterministic_and_connected(self):
        graph = self.data['periods']['2024']['map']
        repeated = build_chat_insights(self.messages)['periods']['2024']['map']

        self.assertEqual(graph, repeated)
        self.assertTrue(graph['nodes'])
        self.assertTrue(graph['edges'])
        for node in graph['nodes']:
            self.assertTrue(75 <= node['x'] <= 925)
            self.assertTrue(65 <= node['y'] <= 555)
        edge_pairs = {(edge['source'], edge['target']) for edge in graph['edges']}
        self.assertTrue(any('райден' in pair and 'фурина' in pair for pair in edge_pairs))


if __name__ == '__main__':
    unittest.main()
