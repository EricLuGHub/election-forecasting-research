import json
import unittest
from unittest.mock import patch, MagicMock

from research.client import Client


class GetRetryTests(unittest.TestCase):
    @patch('research.client.time.sleep')
    @patch('research.client.load_key', return_value='test-only-not-a-real-secret')
    def test_get_timeout_retries_once(self, key, sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'ok': True}).encode()
        with patch('research.client.urllib.request.urlopen', side_effect=[TimeoutError(), response]) as request:
            self.assertTrue(Client().get('/test')['ok'])
            self.assertEqual(request.call_count, 2)

    @patch('research.client.time.sleep')
    @patch('research.client.load_key', return_value='test-only-not-a-real-secret')
    def test_get_retry_bounded_and_sanitized(self, key, sleep):
        with patch('research.client.urllib.request.urlopen', side_effect=TimeoutError('private request')) as request:
            with self.assertRaisesRegex(RuntimeError, r'^GET /test: network failure \(TimeoutError\)$'):
                Client().get('/test')
            self.assertEqual(request.call_count, 2)

    @patch('research.client.time.sleep')
    @patch('research.client.load_key', return_value='test-only-not-a-real-secret')
    def test_post_timeout_is_not_retried(self, key, sleep):
        with patch('research.client.urllib.request.urlopen', side_effect=TimeoutError()) as request:
            with self.assertRaises(TimeoutError):
                Client().post('/orders', {'idempotencyKey': 'unit'})
            self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
