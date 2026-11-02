import ast
import configparser
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def translation_keys():
    result = {}
    tree = ast.parse((ROOT / 'message/keys.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        ):
            result[node.targets[0].id] = node.value.value
    return result


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.parsers = {}
        for language in ('ru', 'en'):
            parser = configparser.ConfigParser(allow_no_value=True, delimiters=('=',))
            parser.read(ROOT / f'message/translations/messages_{language}.properties', encoding='utf-8')
            self.parsers[language] = parser
        self.keys = translation_keys()

    def test_static_message_calls_exist_in_both_languages(self):
        missing = []
        paths = list((ROOT / 'handlers').glob('*.py')) + list((ROOT / 'services').glob('*.py'))
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (
                    not isinstance(node, ast.Call)
                    or not isinstance(node.func, ast.Name)
                    or node.func.id != 'message'
                    or len(node.args) < 3
                ):
                    continue
                key_node, section_node = node.args[1], node.args[2]
                key = (
                    self.keys.get(key_node.id) if isinstance(key_node, ast.Name)
                    else key_node.value if isinstance(key_node, ast.Constant) else None
                )
                section = section_node.value if isinstance(section_node, ast.Constant) else None
                if not key or not section:
                    continue
                for language, parser in self.parsers.items():
                    if not parser.has_option(section, key):
                        missing.append(f'{path}:{node.lineno} {language} {section}.{key}')
        self.assertEqual(missing, [])

    def test_legacy_markdown_is_not_used(self):
        paths = list((ROOT / 'handlers').glob('*.py')) + list((ROOT / 'services').glob('*.py'))
        for path in paths:
            self.assertNotIn("parse_mode='Markdown'", path.read_text(encoding='utf-8'), path)

    def test_percent_similarity_is_literal_in_both_languages(self):
        from message.keys import tag_suggest
        from message.loader import message

        for language in ('RU', 'EN'):
            with self.subTest(language=language):
                rendered = message(language, tag_suggest, 'tag', 'еимия', '67')
                self.assertIn('еимия', rendered)
                self.assertIn('67%', rendered)
