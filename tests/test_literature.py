import unittest
from unittest.mock import patch, MagicMock

from research.literature import PAPERS, DATASETS, fetch_pdf, fetch_asset


class LiteratureTests(unittest.TestCase):
    def test_registry_has_unique_names_and_public_https_urls(self):
        names = [p[0] for p in PAPERS] + [d[0] for d in DATASETS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(p[-1].startswith('https://') for p in PAPERS + DATASETS))
        self.assertTrue(all('proxy' not in p[-1] for p in PAPERS + DATASETS))

    @patch('research.literature.fetch_asset')
    def test_pdf_rejects_login_html(self, fetch):
        fetch.return_value = (b'<html>Login required</html>', 'https://example.org/login')
        with self.assertRaises(ValueError):
            fetch_pdf('https://example.org/paper')

    @patch('research.literature.fetch_asset')
    def test_pdf_preserves_original_bytes_and_final_url(self, fetch):
        expected = (b'%PDF-1.7\noriginal', 'https://example.org/paper.pdf')
        fetch.return_value = expected
        self.assertEqual(fetch_pdf('https://example.org/paper'), expected)

    @patch('research.literature.urlopen')
    def test_response_size_limit(self, urlopen):
        response = MagicMock()
        response.read.return_value = b'x' * 25_000_001
        urlopen.return_value.__enter__.return_value = response
        with self.assertRaises(ValueError):
            fetch_asset('https://example.org/large')


if __name__ == '__main__':
    unittest.main()
