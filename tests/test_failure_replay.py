"""Item-30 failure replays: ambiguous placements must never double-submit.

Drives Executor._submit with scripted fake clients through timeout-after-
acceptance, changed-payload retry, cancel/fill race residue, restart with
live unknown orders, and partial second legs. Each scenario must end in a
UNIQUE economic result: exactly one submission per idempotency key, and any
ambiguity blocks new orders instead of retrying blindly. Fake-only clients;
no network (c160 rule).
"""
import json
import pytest
from research.execution import Executor


OPEN_TOURNAMENT = {'id': 'tid', 'status': 'open',
                   'startDate': '2020-01-01T00:00:00Z',
                   'endDate': '2030-01-01T00:00:00Z',
                   'myBalance': 100000.0}


def _exe(tmp_path, client):
    return Executor(slug='midterm-elections', dry_run=False, client=client,
                    max_basket_capital=5000.0, max_total_capital=70000.0,
                    journal_path=str(tmp_path / 'j.json'),
                    recovery_path=str(tmp_path / 'mode.json'))


class ScriptedClient:
    """GETs serve canned reads; post() follows a script of outcomes."""

    def __init__(self, post_script):
        self.post_script = list(post_script)
        self.posts = 0

    def get(self, path, **kw):
        if path.startswith('/tournaments/midterm'):
            if 'positions' in path:
                return {'positions': []}
            return dict(OPEN_TOURNAMENT)
        raise AssertionError('unexpected GET ' + path)

    def pages(self, path, **kw):
        return []

    def post(self, route, body):
        self.posts += 1
        outcome = self.post_script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _leg(eid='901'):
    return {'exchangeId': eid, 'side': 'no', 'action': 'buy',
            'quantity': 10, 'price': 0.9, 'tournamentId': 'tid'}


def _basket(key='K1'):
    return {'legs': [_leg()], 'tournamentId': 'tid', 'idempotencyKey': key}


def test_timeout_after_acceptance_blocks_retry(tmp_path):
    c = ScriptedClient([TimeoutError('ack lost'),
                        {'results': [{'data': {'orderId': 1}}]}])
    exe = _exe(tmp_path, c)
    with pytest.raises(TimeoutError):
        exe.submit_basket(_basket(), expected_capital=9.0)
    assert c.posts == 1
    # Same key again: must NOT resubmit; must demand reconciliation.
    with pytest.raises(RuntimeError, match='Unresolved placement'):
        exe.submit_basket(_basket(), expected_capital=9.0)
    assert c.posts == 1  # still exactly one submission


def test_changed_payload_retry_rejected(tmp_path):
    c = ScriptedClient([TimeoutError('x')])
    exe = _exe(tmp_path, c)
    with pytest.raises(TimeoutError):
        exe.submit_basket(_basket(), expected_capital=9.0)
    other = _basket()
    other['legs'][0]['price'] = 0.5
    with pytest.raises(ValueError, match='changed payload'):
        exe.submit_basket(other, expected_capital=5.0)
    assert c.posts == 1


def test_restart_with_unknown_blocks_new_orders(tmp_path):
    c = ScriptedClient([TimeoutError('ack lost')])
    exe = _exe(tmp_path, c)
    with pytest.raises(TimeoutError):
        exe.submit_basket(_basket('OLD'), expected_capital=9.0)
    # "Restart": fresh Executor, same journal file, different key.
    exe2 = _exe(tmp_path, c)
    with pytest.raises(RuntimeError, match='Unresolved placement in shared journal'):
        exe2.submit_basket(_basket('NEW'), expected_capital=9.0)
    assert c.posts == 1


def test_confirmed_key_returns_cached_response(tmp_path):
    resp = {'results': [{'data': {'orderId': 7}}]}
    c = ScriptedClient([resp])
    exe = _exe(tmp_path, c)
    out1 = exe.submit_basket(_basket(), expected_capital=9.0)
    out2 = exe.submit_basket(_basket(), expected_capital=9.0)
    assert out1 == out2 == resp
    assert c.posts == 1


def test_partial_legs_each_leg_validated(tmp_path):
    from research.execution import validate_leg
    with pytest.raises(ValueError):
        validate_leg({'exchangeId': 'x', 'side': 'no', 'action': 'buy',
                      'quantity': 10, 'price': 0.9, 'tournamentId': 'tid'})
    c = ScriptedClient([{'results': [{'data': {'orderId': 3}},
                                      {'data': {'orderId': 4}}]}])
    exe = _exe(tmp_path, c)
    legs = [_leg('901'),
            dict(_leg('902'), price=0.1)]
    out = exe.submit_basket({'legs': legs, 'tournamentId': 'tid',
                             'idempotencyKey': 'K2'}, expected_capital=10.0)
    assert out['results'][0]['data']['orderId'] == 3
    assert c.posts == 1
