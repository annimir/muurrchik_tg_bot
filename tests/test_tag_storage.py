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

    def test_find_is_case_insensitive(self):
        storage = TagStorage()
        storage.add_to_cache('Персонаж')

        self.assertEqual(storage.find('пЕРСОНАЖ')['tag'], 'Персонаж')


class ValidationTests(unittest.TestCase):
    def test_length_limits(self):
        self.assertFalse(name_is_too_long('x' * 100))
        self.assertTrue(name_is_too_long('x' * 101))
        self.assertFalse(text_is_too_long('x' * 600))
        self.assertTrue(text_is_too_long('x' * 601))
