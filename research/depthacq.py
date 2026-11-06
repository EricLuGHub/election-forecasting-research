"""Shallow-to-deep book acquisition (backlog item 25).

Screen with shallow books, deepen only when the candidate or held position
needs more size. Same resulting book as a direct deep fetch; fewer levels
cross the wire in the common case. Decision-boundary reads (fire verification,
exit execution) bypass escalation with explicit full depth.
"""
import argparse
import json

LEVELS = (5, 20, 50)


def depth_needed(bids, size):
    """Shares fillable from these bid levels alone."""
    avail = 0.0
    for x in bids or []:
        try:
            avail += float(x.get('quantity', 0))
        except (TypeError, ValueError):
            continue
        if avail >= size:
            break
    return avail


def acquire_book(client, tid, eid, size=0, levels=LEVELS):
    """(book, depth_used). Escalates until size fills or levels exhaust."""
    book, used = None, 0
    for depth in levels:
        book = client.get(f'/exchanges/{eid}/orderbook',
                          tournamentId=tid, depth=depth)
        used = depth
        if size <= 0 or depth_needed(book.get('bids', []), size) >= size:
            break
    return book, used
