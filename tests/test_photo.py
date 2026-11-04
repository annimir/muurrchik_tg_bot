import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram import InputFile

from config.config import config
from services.photo import photo_input


class PhotoInputTests(unittest.TestCase):
    def test_telegram_file_id_is_unchanged(self):
        self.assertEqual(photo_input('telegram-file-id'), 'telegram-file-id')

    def test_path_is_sent_as_binary_input_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'placeholder.png'
            path.write_bytes(b'placeholder-image')

            result = photo_input(path)

        self.assertIsInstance(result, InputFile)
        self.assertEqual(result.filename, 'placeholder.png')
        self.assertEqual(result.input_file_content, b'placeholder-image')

    def test_local_photo_is_read_from_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            uploads = Path(directory) / 'uploads'
            uploads.mkdir()
            (uploads / 'character.png').write_bytes(b'local-character-image')
            with patch.object(config, 'web_media_cache_dir', directory):
                result = photo_input('local:character.png')

        self.assertIsInstance(result, InputFile)
        self.assertEqual(result.filename, 'character.png')
        self.assertEqual(result.input_file_content, b'local-character-image')


if __name__ == '__main__':
    unittest.main()
