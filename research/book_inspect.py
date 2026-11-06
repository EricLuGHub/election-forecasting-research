"""Read-only book inspection. Derived previews stay in ignored data/books/.

Run with data/research-venv/bin/python -m research.book_inspect.
Requires PyMuPDF; never copies source PDFs into the repository.
"""
import argparse
import json
from pathlib import Path

import fitz

from .client import ROOT

BOOKS = {
    'superforecasting': ('philip_e._tetlock_-_superforecasting_the_art_and_science_of_prediction.pdf', [43, 44, 185, 186, 187, 188, 189]),
    'harris': ('Trading-Exchanges-Market-Microstructure-Practitioners Draft Copy.pdf', [9, 14, 15, 16]),
    'ohara': ("Maureen O'Hara - Market Microstructure Theory  -Wiley (1998).pdf", [6, 7, 8, 10, 11]),
    'poker': ('the-mathematics-of-poker_compress.pdf', [288, 297, 298, 299, 300, 301, 302]),
    'masters': ('testing-and-tuning-market-trading-systems-algorithms-in-c-9781484241738-1484241738.pdf', [5, 6, 7, 14, 15, 140, 141]),
    'wizards': ('41775536-Market-Wizards.pdf', [70, 71, 162]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, default=Path.home() / 'Downloads')
    args = parser.parse_args()
    directory = ROOT / 'data/books'
    directory.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name, (filename, pages) in BOOKS.items():
        source = args.downloads / filename
        if not source.is_file():
            inventory.append({'title': name, 'source': str(source), 'status': 'missing'})
            continue
        with fitz.open(source) as doc:
            item = {'title': name, 'source': str(source), 'pageCount': len(doc),
                    'inspectedPdfPages': pages, 'toc': doc.get_toc(), 'excerpts': []}
            for number in pages:
                page = doc[number-1]
                item['excerpts'].append({'pdfPage': number, 'text': page.get_text()})
            # One selected page per book, plus image-only books' contents.
            render = pages[:3] if name in ('ohara', 'poker') else pages[:1]
            for number in render:
                doc[number-1].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(directory / f'{name}-{number}.png')
            (directory / f'{name}.json').write_text(json.dumps(item, indent=2))
            inventory.append({k: v for k, v in item.items() if k != 'excerpts'})
    (directory / 'inventory.json').write_text(json.dumps(inventory, indent=2))
    print(json.dumps([{k: v for k, v in x.items() if k != 'toc'} for x in inventory], indent=2))


if __name__ == '__main__':
    main()
