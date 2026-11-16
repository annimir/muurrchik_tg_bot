import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from services.tierlist_catalog import get_tierlist_filter_options, list_tierlist_characters
from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


class TierListCatalogTests(unittest.TestCase):
    def test_catalog_has_unique_complete_characters_and_local_images(self):
        characters = list_tierlist_characters()
        self.assertGreater(len(characters), 100)
        self.assertEqual(len(characters), len({character['id'] for character in characters}))
        for character in characters:
            with self.subTest(character=character['id']):
                self.assertEqual(character['game'], 'genshin')
                self.assertIn(character['rarity'], {4, 5})
                for key in ('name', 'region', 'element', 'gender'):
                    self.assertTrue(character[key], key)
                    if key != 'name':
                        self.assertTrue(character[key]['id'])
                        self.assertTrue(character[key]['name'])
                        self.assertFalse(character[key]['name'].isupper())
                image = Path('web', character['image'].removeprefix('/'))
                self.assertTrue(image.is_file(), image)
                self.assertGreater(image.stat().st_size, 1000)

    def test_affiliations_are_separate_from_regions_and_have_filter_options(self):
        characters = list_tierlist_characters()
        fatui = {
            character['id']
            for character in characters
            if 'fatui' in {
                affiliation['id'] for affiliation in character.get('affiliations', [])
            }
        }
        self.assertTrue({
            'tartaglia', 'lynette', 'lyney', 'freminet', 'arlecchino',
            'columbina', 'sandrone',
        } <= fatui)
        self.assertNotIn('fatui', {character['region']['id'] for character in characters})
        for character in characters:
            for affiliation in character.get('affiliations', []):
                self.assertTrue(affiliation['id'])
                self.assertTrue(affiliation['name'])

        options = get_tierlist_filter_options(['genshin'])['affiliation']
        self.assertEqual(
            [(option['id'], option['name']) for option in options],
            [('house_of_the_hearth', 'Дом очага'), ('fatui', 'Фатуи')],
        )


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class TierListWebIntegrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        queries.db("INSERT INTO games (code, name) VALUES ('genshin', 'Genshin Impact')").close()
        from web.app import create_app
        from web.auth import SESSION_COOKIE, create_admin_session

        self.client = TestClient(create_app())
        self.user = queries.ensure_user(100, 'player')
        token, self.csrf = create_admin_session(100)
        self.cookie_name = SESSION_COOKIE
        self.cookie = token

    def tearDown(self):
        self.client.close()

    def login(self):
        self.client.cookies.set(self.cookie_name, self.cookie)

    def create_list(self, title='Мои любимчики'):
        self.login()
        response = self.client.post(
            '/tierlists',
            data={'title': title, 'games': 'genshin', 'csrf_token': self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return int(response.headers['location'].split('/')[2])

    def ordered_entries(self, tier_list):
        ranked = {'furina': 'S', 'raiden_shogun': 'A'}
        return [
            {'character_id': character['id'], 'tier': ranked.get(character['id'], 'UNRANKED')}
            for character in list_tierlist_characters(['genshin'])
        ]

    def test_create_save_public_profile_conflict_and_delete(self):
        from database.tierlists import get_tier_list

        queries.db(
            "INSERT INTO user_games (user_id, game_code) VALUES (%s, 'genshin')",
            (self.user['id'],),
        ).close()
        self.login()
        new_page = self.client.get('/tierlists/new')
        self.assertEqual(new_page.status_code, 200)
        self.assertIn('value="genshin" checked', new_page.text)

        tier_list_id = self.create_list()
        second_id = self.create_list('Сила в мете')
        tier_list = get_tier_list(tier_list_id, self.user['id'])
        self.assertEqual(len(tier_list['entries']), len(list_tierlist_characters(['genshin'])))
        self.assertEqual({entry['tier'] for entry in tier_list['entries']}, {'UNRANKED'})

        editor = self.client.get(f'/tierlists/{tier_list_id}/edit')
        self.assertEqual(editor.status_code, 200)
        self.assertIn('data-filter="region"', editor.text)
        self.assertIn('data-filter="element"', editor.text)
        self.assertIn('data-filter="gender"', editor.text)
        self.assertIn('data-filter="affiliation"', editor.text)
        self.assertIn('<option value="fatui">Фатуи</option>', editor.text)
        self.assertIn('data-region="snezhnaya" data-element="hydro"', editor.text)
        self.assertIn('data-affiliation="fatui house_of_the_hearth"', editor.text)
        self.assertIn('data-move-tier="S"', editor.text)

        response = self.client.post(
            f'/tierlists/{tier_list_id}',
            data={
                'title': 'Обновлённый рейтинг', 'games': 'genshin',
                'entries': json.dumps(self.ordered_entries(tier_list)),
                'version': 1, 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'ok': True, 'version': 2})
        updated = get_tier_list(tier_list_id, self.user['id'])
        by_character = {entry['character_id']: entry for entry in updated['entries']}
        self.assertEqual(by_character['furina']['tier'], 'S')
        self.assertEqual(by_character['raiden_shogun']['tier'], 'A')
        self.assertEqual(by_character['furina']['position'], 0)

        stale = self.client.post(
            f'/tierlists/{tier_list_id}',
            data={
                'title': 'Конфликт', 'games': 'genshin',
                'entries': json.dumps(self.ordered_entries(updated)),
                'version': 1, 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(stale.status_code, 409)

        own_lists = self.client.get('/tierlists/mine')
        self.assertIn('Обновлённый рейтинг', own_lists.text)
        self.assertIn('Сила в мете', own_lists.text)

        self.client.cookies.clear()
        gallery = self.client.get('/tierlists')
        self.assertEqual(gallery.status_code, 200)
        self.assertIn('Публичные рейтинги', gallery.text)
        self.assertIn('Обновлённый рейтинг', gallery.text)
        self.assertIn('class="tierlist-preview"', gallery.text)
        self.assertIn('/static/tierlists/characters/furina.webp', gallery.text)
        self.assertIn('Автор: player', gallery.text)
        self.assertNotIn('Автор: @player', gallery.text)
        self.assertIn(f'2/{len(list_tierlist_characters(["genshin"]))}', gallery.text)
        self.assertIn('class="tierlist-card-footer"', gallery.text)
        self.assertNotIn('Создать тирлист', gallery.text)
        self.login()
        account_gallery = self.client.get('/tierlists')
        self.assertIn('Создать тирлист', account_gallery.text)
        self.assertLess(
            account_gallery.text.index('Создать тирлист'),
            account_gallery.text.index('Мои тирлисты</a>'),
        )
        self.client.cookies.clear()
        mine_redirect = self.client.get('/tierlists/mine', follow_redirects=False)
        self.assertEqual(mine_redirect.status_code, 303)
        self.assertEqual(mine_redirect.headers['location'], '/tierlists/login')

        public = self.client.get(f'/tierlists/{tier_list_id}')
        self.assertEqual(public.status_code, 200)
        self.assertIn('Обновлённый рейтинг', public.text)
        self.assertIn('Фурина', public.text)
        self.assertIn('Райдэн', public.text)
        self.assertIn('data-tierlist-filters', public.text)
        self.assertIn('data-filter="region"', public.text)
        self.assertIn('data-filter="element"', public.text)
        self.assertIn('data-filter="gender"', public.text)
        self.assertIn('data-filter="affiliation"', public.text)
        self.assertIn('data-character-id="furina"', public.text)
        self.assertIn('data-region="fontaine"', public.text)
        self.assertNotIn('Барбара', public.text)
        self.assertNotIn('Без тира', public.text)

        profile = self.client.get(f'/users/{self.user["id"]}')
        self.assertIn('Обновлённый рейтинг', profile.text)
        self.assertIn('Сила в мете', profile.text)
        self.assertIn('class="tierlist-preview"', profile.text)
        self.assertIn(f'href="/tierlists/{tier_list_id}"', profile.text)
        login_redirect = self.client.get(f'/tierlists/{tier_list_id}/edit', follow_redirects=False)
        self.assertEqual(login_redirect.status_code, 303)
        self.assertEqual(login_redirect.headers['location'], '/tierlists/login')

        self.login()
        response = self.client.post(
            f'/tierlists/{tier_list_id}/delete', data={'csrf_token': 'wrong'},
        )
        self.assertEqual(response.status_code, 403)
        deleted = self.client.post(
            f'/tierlists/{tier_list_id}/delete',
            data={'csrf_token': self.csrf}, follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f'/tierlists/{tier_list_id}').status_code, 404)
        self.assertEqual(self.client.get(f'/tierlists/{second_id}').status_code, 200)

    def test_public_tierlists_filter_by_multiple_players(self):
        from database.tierlists import create_tier_list

        first = queries.ensure_user(200, 'alpha')
        second = queries.ensure_user(300, 'beta')
        third = queries.ensure_user(400, 'gamma')
        create_tier_list(first['id'], 'Альфа-лист', ['genshin'])
        create_tier_list(second['id'], 'Бета-лист', ['genshin'])
        create_tier_list(third['id'], 'Гамма-лист', ['genshin'])

        response = self.client.get(f'/tierlists?player={first["id"]}&player={second["id"]}')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Альфа-лист', response.text)
        self.assertIn('Бета-лист', response.text)
        self.assertNotIn('Гамма-лист', response.text)
        self.assertEqual(response.text.count('name="player"'), 3)
        self.assertIn(f'value="{first["id"]}" checked', response.text)
        self.assertIn(f'value="{second["id"]}" checked', response.text)
        self.assertIn('alpha, beta', response.text)
        self.assertNotIn('Автор: @', response.text)

    def test_foreign_list_is_not_editable_and_validation_is_applied(self):
        other = queries.ensure_user(200, 'other')
        from database.tierlists import create_tier_list, get_tier_list

        foreign = create_tier_list(other['id'], 'Чужой рейтинг', ['genshin'])
        self.login()
        self.assertEqual(self.client.get(f'/tierlists/{foreign["id"]}/edit').status_code, 404)
        self.assertEqual(
            self.client.post(
                '/tierlists',
                data={'title': '', 'games': 'genshin', 'csrf_token': self.csrf},
            ).status_code,
            400,
        )
        tier_list_id = self.create_list()
        current = get_tier_list(tier_list_id, self.user['id'])
        response = self.client.post(
            f'/tierlists/{tier_list_id}',
            data={
                'title': 'Неполная раскладка', 'games': 'genshin', 'entries': '[]',
                'version': current['lock_version'], 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('всех персонажей', response.json()['detail'])
