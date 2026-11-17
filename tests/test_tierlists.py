import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
                self.assertIn(character.get('availability', 'playable'), {'playable', 'upcoming', 'npc'})
                if character['rarity'] is not None:
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
        option_values = [(option['id'], option['name']) for option in options]
        self.assertEqual(option_values, sorted(option_values, key=lambda item: item[1].casefold()))
        self.assertTrue({
            ('house_of_the_hearth', 'Дом очага'),
            ('fatui', 'Фатуи'),
            ('hexenzirkel', 'Ведьмин шабаш'),
            ('five_sinners', 'Пять грешников'),
            ('four_shades', 'Четыре тени'),
            ('moon_goddesses', 'Богини Луны'),
        } <= set(option_values))

    def test_npc_and_upcoming_characters_have_explicit_availability(self):
        characters = {character['id']: character for character in list_tierlist_characters()}
        upcoming = {'anastasya', 'danica'}
        npc = {
            'noy', 'alice', 'dainsleif', 'pantalone', 'pierro', 'dottore',
            'barbeloth', 'rhinedottir', 'naberius', 'ronova', 'astaroth',
            'asmoday', 'capitano', 'pulcinella', 'signora', 'aria', 'canon',
            'sonnet', 'rerir',
        }
        self.assertEqual(
            {character['id'] for character in characters.values()
             if character.get('availability') == 'upcoming'},
            upcoming,
        )
        self.assertEqual(
            {character['id'] for character in characters.values()
             if character.get('availability') == 'npc'},
            npc,
        )
        self.assertIn('astaroth', characters)
        self.assertNotIn('istaroth', characters)
        self.assertNotEqual(characters['rhinedottir'], characters['naberius'])
        for character_id in npc:
            self.assertIsNone(characters[character_id]['rarity'])
        expected_elements = {
            'anastasya': 'cryo', 'danica': 'electro', 'noy': 'dendro',
            'alice': 'pyro', 'dainsleif': 'pyro', 'pantalone': 'dendro',
            'pierro': 'electro', 'barbeloth': 'hydro', 'capitano': 'cryo',
            'pulcinella': 'hydro', 'signora': 'pyro',
        }
        for character_id, element_id in expected_elements.items():
            self.assertEqual(characters[character_id]['element']['id'], element_id)
        for character_id in ('aria', 'canon', 'sonnet'):
            self.assertEqual(
                characters[character_id]['affiliations'][0]['id'], 'moon_goddesses',
            )
        self.assertIn(
            'five_sinners',
            {affiliation['id'] for affiliation in characters['rerir']['affiliations']},
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
        self.assertIn('data-filter="availability"', editor.text)
        self.assertIn('data-availability="npc"', editor.text)
        self.assertIn('>NPC</span>', editor.text)
        self.assertIn('>Скоро</span>', editor.text)
        self.assertNotIn('None★', editor.text)
        self.assertIn('<option value="fatui">Фатуи</option>', editor.text)
        self.assertIn('data-region="snezhnaya" data-element="hydro"', editor.text)
        self.assertIn('data-affiliation="fatui house_of_the_hearth"', editor.text)
        self.assertIn('data-move-tier="S"', editor.text)

        response = self.client.post(
            f'/tierlists/{tier_list_id}',
            data={
                'title': 'Обновлённый рейтинг', 'games': 'genshin',
                'entries': json.dumps(self.ordered_entries(tier_list)),
                'tier_descriptions': json.dumps({
                    'S': 'Лучшие из лучших', 'A': 'Очень сильные',
                }),
                'version': 1, 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(), {'ok': True, 'version': 2, 'notification_sent': False},
        )
        updated = get_tier_list(tier_list_id, self.user['id'])
        by_character = {entry['character_id']: entry for entry in updated['entries']}
        self.assertEqual(by_character['furina']['tier'], 'S')
        self.assertEqual(by_character['raiden_shogun']['tier'], 'A')
        self.assertEqual(by_character['furina']['position'], 0)
        self.assertEqual(
            updated['tier_descriptions'],
            {'S': 'Лучшие из лучших', 'A': 'Очень сильные'},
        )

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
        self.assertIn('data-tier-description-text>Лучшие из лучших</p>', public.text)
        self.assertIn('data-tier-description-text>Очень сильные</p>', public.text)
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

    def test_legacy_list_is_completed_with_new_unranked_characters(self):
        from database.tierlists import get_tier_list

        tier_list_id = self.create_list()
        missing_ids = ['capitano', 'rerir']
        queries.db(
            '''
            DELETE FROM tier_list_entry
            WHERE tier_list_id = %s AND character_id = ANY(%s)
            ''',
            (tier_list_id, missing_ids),
        ).close()
        queries.db(
            'UPDATE tier_list SET lock_version = 2 WHERE id = %s',
            (tier_list_id,),
        ).close()

        editor = self.client.get(f'/tierlists/{tier_list_id}/edit')
        self.assertEqual(editor.status_code, 200)
        for character_id in missing_ids:
            self.assertIn(f'data-character-id="{character_id}"', editor.text)

        tier_list = get_tier_list(tier_list_id, self.user['id'])
        entries = [
            entry for entry in self.ordered_entries(tier_list)
            if entry['character_id'] not in missing_ids
        ]
        with patch(
            'services.tierlist_notifications.announce_tier_list', new=AsyncMock(),
        ) as announce:
            response = self.client.post(
                f'/tierlists/{tier_list_id}',
                data={
                    'title': tier_list['title'], 'games': 'genshin',
                    'entries': json.dumps(entries), 'version': 2,
                    'csrf_token': self.csrf,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        announce.assert_not_awaited()
        updated = get_tier_list(tier_list_id, self.user['id'])
        by_character = {entry['character_id']: entry for entry in updated['entries']}
        self.assertEqual(len(updated['entries']), len(list_tierlist_characters(['genshin'])))
        for character_id in missing_ids:
            self.assertEqual(by_character[character_id]['tier'], 'UNRANKED')
        self.assertEqual(by_character['furina']['tier'], 'S')
        self.assertIsNone(updated['first_saved_at'])

    def test_first_save_announcement_is_retried_and_sent_only_once(self):
        from database.tierlists import get_tier_list, mark_tier_list_announcement_sent

        tier_list_id = self.create_list()

        announcement_results = iter((False, True))

        def announcement_result(tier_list):
            result = next(announcement_results)
            if result:
                mark_tier_list_announcement_sent(tier_list['id'])
            return result

        with patch(
            'services.tierlist_notifications.announce_tier_list',
            new=AsyncMock(side_effect=announcement_result),
        ) as announce:
            for expected_version, expected_notification in ((2, False), (3, True)):
                tier_list = get_tier_list(tier_list_id, self.user['id'])
                response = self.client.post(
                    f'/tierlists/{tier_list_id}',
                    data={
                        'title': 'Новый рейтинг', 'games': 'genshin',
                        'entries': json.dumps(self.ordered_entries(tier_list)),
                        'version': tier_list['lock_version'], 'csrf_token': self.csrf,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['version'], expected_version)
                self.assertIs(response.json()['notification_sent'], expected_notification)

            tier_list = get_tier_list(tier_list_id, self.user['id'])
            self.assertIsNotNone(tier_list['first_saved_at'])
            self.assertIsNotNone(tier_list['announcement_sent_at'])
            response = self.client.post(
                f'/tierlists/{tier_list_id}',
                data={
                    'title': 'Отредактированный рейтинг', 'games': 'genshin',
                    'entries': json.dumps(self.ordered_entries(tier_list)),
                    'version': tier_list['lock_version'], 'csrf_token': self.csrf,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('notification_sent', response.json())

        self.assertEqual(announce.await_count, 2)
        announced_tier_list = announce.await_args.args[0]
        self.assertEqual(announced_tier_list['owner_tag'], 'player')
        self.assertEqual(announced_tier_list['title'], 'Новый рейтинг')

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
                'title': 'Некорректная раскладка', 'games': 'genshin',
                'entries': json.dumps([{'character_id': 'unknown', 'tier': 'S'}]),
                'version': current['lock_version'], 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('не соответствуют', response.json()['detail'])

        response = self.client.post(
            f'/tierlists/{tier_list_id}',
            data={
                'title': 'Длинное описание', 'games': 'genshin',
                'entries': json.dumps(self.ordered_entries(current)),
                'tier_descriptions': json.dumps({'S': 'x' * 301}),
                'version': current['lock_version'], 'csrf_token': self.csrf,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('не более 300 символов', response.json()['detail'])

    async def test_telegram_announcement_payload_and_delivery_marker(self):
        from database.tierlists import create_tier_list, get_tier_list
        from services.tierlist_notifications import announce_tier_list

        queries.upsert_chat(-100500, 'Основной чат')
        tier_list = create_tier_list(self.user['id'], 'Рейтинг для чата', ['genshin'])
        response = MagicMock()
        response.json.return_value = {'ok': False}
        http_client = MagicMock()
        http_client.__aenter__ = AsyncMock(return_value=http_client)
        http_client.__aexit__ = AsyncMock(return_value=False)
        http_client.post = AsyncMock(return_value=response)

        with patch(
            'services.tierlist_notifications.httpx.AsyncClient', return_value=http_client,
        ):
            self.assertFalse(await announce_tier_list(tier_list))
            saved = get_tier_list(tier_list['id'], self.user['id'])
            self.assertIsNone(saved['announcement_sent_at'])

            response.json.return_value = {'ok': True}
            self.assertTrue(await announce_tier_list(tier_list))

        saved = get_tier_list(tier_list['id'], self.user['id'])
        self.assertIsNotNone(saved['announcement_sent_at'])
        request = http_client.post.await_args.kwargs['json']
        self.assertEqual(request['chat_id'], -100500)
        self.assertEqual(request['text'], 'player создал тирлист «Рейтинг для чата»')
        self.assertEqual(
            request['reply_markup']['inline_keyboard'][0][0]['url'],
            f'http://testserver/tierlists/{tier_list["id"]}',
        )
