import unittest

from services.tag_storage import TagStorage
from services.validation import name_is_too_long, text_is_too_long


class TagStorageTests(unittest.TestCase):
    def test_rename_updates_main_name_and_aliases(self):
        storage = TagStorage()
        storage.load_from(['Main'])
        storage.load_aliases([('Alias', 'Main')])

        storage.rename('Main', 'Renamed')

        self.assertEqual(storage.find('main'), {'status': 'found', 'tag': 'Renamed'})
        self.assertEqual(storage.find('alias'), {'status': 'found', 'tag': 'Renamed'})

    def test_replace_removes_stale_tags_and_aliases(self):
        storage = TagStorage()
        storage.load_from(['Old'])
        storage.load_aliases([('Alias', 'Old')])

        storage.replace(['New'], [('Other', 'New')])

        self.assertEqual(storage.find('old')['status'], 'created')
        self.assertEqual(storage.find('alias')['status'], 'created')
        self.assertEqual(storage.find('other'), {'status': 'found', 'tag': 'New'})

    def test_find_is_case_insensitive(self):
        storage = TagStorage()
        storage.add_to_cache('Персонаж')

        self.assertEqual(storage.find('пЕРСОНАЖ')['tag'], 'Персонаж')

    def test_case_and_yo_variants_match_existing_tag(self):
        storage = TagStorage()
        storage.load_from(['Кейя', 'Филёл'])

        self.assertEqual(storage.find('кеия'), {'status': 'suggest', 'tag': 'Кейя', 'score': 100.0})
        self.assertEqual(storage.find('филел'), {'status': 'suggest', 'tag': 'Филёл', 'score': 100.0})
        self.assertEqual(storage.find('филёл'), {'status': 'found', 'tag': 'Филёл'})

    def test_unrelated_short_name_is_created_without_suggestion(self):
        storage = TagStorage()
        storage.load_from(['еимия', 'ЯэМико'])

        self.assertEqual(storage.find('Митя'), {'status': 'created', 'tag': 'Митя'})

    def test_repeated_letters_suggest_existing_tag(self):
        storage = TagStorage()
        storage.add_to_cache('Арлекино')

        result = storage.find('Арлекииино')

        self.assertEqual(result['status'], 'suggest')
        self.assertEqual(result['tag'], 'Арлекино')
        self.assertGreaterEqual(result['score'], 85)

    def test_repeated_letters_in_short_name_suggest_existing_tag(self):
        storage = TagStorage()
        storage.add_to_cache('митя')

        result = storage.find('мииитяя')

        self.assertEqual(result, {'status': 'suggest', 'tag': 'митя', 'score': 100.0})

    def test_repeated_letters_prefer_shortest_canonical_tag(self):
        storage = TagStorage()
        storage.load_from(['митя', 'мииитяя'])

        result = storage.find('ммииииттяяя')

        self.assertEqual(result, {'status': 'suggest', 'tag': 'митя', 'score': 100.0})


class ValidationTests(unittest.TestCase):
    def test_length_limits(self):
        self.assertFalse(name_is_too_long('x' * 100))
        self.assertTrue(name_is_too_long('x' * 101))
        self.assertFalse(text_is_too_long('x' * 600))
        self.assertTrue(text_is_too_long('x' * 601))
