from contextlib import closing
import io
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import max_bot


class MaxBotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.receipts = Path(self.directory.name) / 'events.sqlite3'
        self.config = {'site_url': 'https://school.example/', 'username': 'school_bot',
                       'secret': 'x' * 40, 'token': 'fake-token-for-tests'}
        self.sent = []
        self.update = {'update_type': 'bot_started', 'timestamp': 1_000_000,
                       'chat_id': 42, 'user': {'user_id': 7, 'is_bot': False}}

    def tearDown(self):
        self.directory.cleanup()

    def run_update(self, update=None, now=1000):
        max_bot.process_update(self.config, self.update if update is None else update,
                               sender=lambda *args: self.sent.append(args),
                               now=now, receipts=self.receipts)

    def test_start_and_duplicate(self):
        self.run_update()
        self.run_update()
        self.assertEqual(len(self.sent), 1)
        button = self.sent[0][3]['attachments'][0]['payload']['buttons'][0][0]
        self.assertEqual(button['type'], 'link')
        self.assertEqual(button['url'], self.config['site_url'])

    def test_open_app_requires_explicit_registration(self):
        self.config['webapp_registered'] = True
        button = max_bot.reply_body(self.config)['attachments'][0]['payload']['buttons'][0][0]
        self.assertEqual(button['type'], 'open_app')
        self.assertEqual(button['web_app'], 'school_bot')
        self.assertNotIn('url', button)

    def test_ignore_expired_future_bot_and_unrelated_updates(self):
        self.run_update(now=40000)
        self.run_update(now=0)
        self.run_update({**self.update, 'user': {'is_bot': True}})
        self.run_update({'update_type': 'user_added'})
        self.assertEqual(self.sent, [])

    def test_private_help_and_safe_fallback(self):
        update = {'update_type': 'message_created', 'timestamp': 1_000_000,
                  'message': {'sender': {'is_bot': False},
                              'recipient': {'chat_type': 'dialog', 'chat_id': 43},
                              'body': {'text': '/help', 'mid': 'mid-1'}}}
        self.run_update(update)
        self.assertEqual(len(self.sent), 1)
        update['message']['body'] = {'text': 'personal-code', 'mid': 'mid-2'}
        self.run_update(update, now=1010)
        update['message']['body'] = {'text': '/start', 'mid': 'mid-3'}
        update['message']['recipient']['chat_type'] = 'chat'
        self.run_update(update, now=1020)
        self.assertEqual(len(self.sent), 2)
        self.assertIn('мини-приложении', self.sent[-1][3]['text'])
        self.assertNotIn('personal-code', self.sent[-1][3]['text'])
        self.assertNotIn(b'personal-code', self.receipts.read_bytes())

    def message(self, text, mid='command-1', user=7, chat=42):
        return {'update_type': 'message_created', 'timestamp': 1_000_000,
                'message': {'sender': {'is_bot': False, 'user_id': user},
                            'recipient': {'chat_type': 'dialog', 'chat_id': chat},
                            'body': {'text': text, 'mid': mid}}}

    def test_menu_and_readable_help(self):
        menu = max_bot.reply_body(self.config)
        rows = menu['attachments'][0]['payload']['buttons']
        self.assertEqual(rows[0][0]['text'], 'Открыть платформу')
        self.assertEqual([b['text'] for b in rows[1]], ['Помощь', 'Подключение'])
        self.run_update(self.message('Помощь'))
        self.assertIn('/stop', self.sent[-1][3]['text'])
        self.run_update(self.message('О проекте', 'about'), now=1002)
        self.assertIn('вклад ученика', self.sent[-1][3]['text'])
        self.run_update(self.message('???', 'fallback'), now=1010)
        self.run_update(self.message('ещё текст', 'fallback-2'), now=1011)
        self.assertEqual(len(self.sent), 3, 'unknown text is rate limited')

    def test_status_is_private_to_max_account_and_chat(self):
        database = Path(self.directory.name) / 'school.sqlite3'
        with closing(sqlite3.connect(database)) as c, c:
            c.executescript("CREATE TABLE users(id TEXT,name TEXT,role TEXT);"
                            "CREATE TABLE account_access(user_id TEXT,active INTEGER);"
                            "CREATE TABLE max_links(user_id TEXT,max_user_id INTEGER,chat_id INTEGER);"
                            "INSERT INTO users VALUES('school-1','Демо Ученик','student');"
                            "INSERT INTO account_access VALUES('school-1',1);"
                            "INSERT INTO max_links VALUES('school-1',7,42);")
        for user, chat, connected in [(7,42,True),(8,42,False),(7,43,False)]:
            result = max_bot.subscription_status(database,user,chat)
            self.assertEqual('Демо Ученик' in result,connected)
        max_bot.process_update(self.config,self.message('Подключение'),
                               sender=lambda *args:self.sent.append(args),
                               now=1000,receipts=self.receipts,database=database)
        self.assertIn('Демо Ученик', self.sent[-1][3]['text'])
        with closing(sqlite3.connect(database)) as c, c:
            c.execute('UPDATE account_access SET active=0')
        self.assertNotIn('Демо Ученик',max_bot.subscription_status(database,7,42))
        self.assertIn('недоступна',max_bot.subscription_status(database,7,42))

    def test_retry_after_api_failure(self):
        with self.assertRaises(max_bot.BotError):
            max_bot.process_update(self.config, self.update, now=1000, receipts=self.receipts,
                                   sender=lambda *args: (_ for _ in ()).throw(max_bot.BotError()))
        self.run_update()
        self.assertEqual(len(self.sent), 1)

    def test_webhook_rejects_forgery_before_reading_body(self):
        class Handler:
            headers = {'X-Max-Bot-Api-Secret': 'wrong', 'Content-Length': '2'}
            rfile = io.BytesIO(b'{}')
            def reply(self, status, body):
                self.status = status
        handler = Handler()
        with patch.object(max_bot, 'load_config', return_value=self.config):
            max_bot.webhook(handler)
        self.assertEqual(handler.status, 403)
        self.assertEqual(handler.rfile.tell(), 0)

    def test_webhook_auth_and_size(self):
        class Handler:
            headers = {'X-Max-Bot-Api-Secret': 'x' * 40, 'Content-Length': '2'}
            rfile = io.BytesIO(b'{}')
            def reply(self, status, body):
                self.status = status
        handler = Handler()
        with patch.object(max_bot, 'load_config', return_value=self.config), \
             patch.object(max_bot, 'process_update') as process:
            max_bot.webhook(handler)
            process.assert_called_once_with(self.config, {})
        self.assertEqual(handler.status, 200)
        handler.headers = {**handler.headers, 'Content-Length': '65537'}
        with patch.object(max_bot, 'load_config', return_value=self.config):
            max_bot.webhook(handler)
        self.assertEqual(handler.status, 413)


if __name__ == '__main__':
    unittest.main()
