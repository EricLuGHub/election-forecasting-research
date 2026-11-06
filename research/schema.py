"""Download the public OpenAPI document embedded in the API reference."""
import json
import urllib.request
from .client import ROOT, save_json


def main():
    with urllib.request.urlopen('https://sig.thesuper.market/api/v1/docs', timeout=30) as response:
        html = response.read().decode()
    schema = json.JSONDecoder().raw_decode(html.split('\"content\":', 1)[1].lstrip())[0]
    save_json(ROOT / 'data/openapi.json', schema)
    print(f'Saved {len(schema["paths"])} documented API paths to data/openapi.json')


if __name__ == '__main__':
    main()
