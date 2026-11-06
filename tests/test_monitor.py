import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from research.monitor import History, Monitor, candidates, exit_liquidity, instance_lock, options, recent, running, top_book


def fixture():
    markets, nodes, books = [], {}, {}
    for mid, party, bid in [('1', 'Republican', .60), ('2', 'Democratic', .50)]:
        markets.append({'id':mid, 'status':'open', 'title':party, 'exchanges':[{'id':mid}]})
        nodes[mid] = {'root':{'node_type':'contract', 'contract_details':
                    {'raceId':'race', 'stageId':'stage', 'resolutionType':'Party Winner',
                     'winnerName':party, 'raceName':'Test race'}}}
        books[mid] = {'exchangeId':mid, 'marketId':mid, 'bestBid':bid, 'bestAsk':bid+.1,
                      'bids':[{'price':bid, 'quantity':1000}], 'asks':[{'price':bid+.1, 'quantity':1000}]}
    return {'startedAt':datetime.now(timezone.utc).isoformat(), 'tournament':{'id':'T','slug':'test', 'status':'draft', 'startDate':None, 'endDate':None},
            'markets':markets, 'nodes':nodes, 'books':books, 'errors':[]}


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.depth_override = None
        self.failed_exchange = None

    def pages(self, path, **params):
        return self.data['markets']

    def get(self, path, **params):
        if path.startswith('/tournaments/'):
            return self.data['tournament']
        if path.endswith('/nodes'):
            return self.data['nodes'][path.split('/')[2]]
        if path == '/exchanges/prices':
            return {'data':[{k:v for k,v in b.items() if k not in ('bids','asks')}
                            for b in self.data['books'].values() if b['exchangeId'] in params['ids'].split(',')], 'missingIds':[]}
        if path.endswith('/orderbook'):
            eid = path.split('/')[2]
            if eid == self.failed_exchange:
                raise RuntimeError('Unavailable')
            return dict((self.depth_override or self.data['books'])[eid])
        raise AssertionError(path)


class MonitorTests(unittest.TestCase):
    def test_exit_uses_other_side_depth_and_requires_all_legs(self):
        data=fixture();c=candidates(data,0)[0]
        result=exit_liquidity(data['books'],c,0)
        self.assertTrue(result['fullExitAvailable'])
        self.assertAlmostEqual(result['netProceeds'],700)
        data['books']['2']['asks']=[]
        result=exit_liquidity(data['books'],c,0)
        self.assertFalse(result['fullExitAvailable'])
        self.assertIsNone(result['netProceeds'])

    def test_bulk_unit_sizes_never_supply_alert_capacity(self):
        data=fixture()
        tops={eid:top_book(b, data['startedAt'], data['startedAt']) for eid,b in data['books'].items()}
        screened=candidates(dict(data, books=tops),0)[0]
        confirmed=candidates(data,0)[0]
        self.assertEqual(screened['quantityEach'],1)
        self.assertEqual(confirmed['quantityEach'],1000)
        self.assertEqual(screened['id'],confirmed['id'])
        self.assertAlmostEqual(confirmed['minimumNetPayoutMinusCost'],100)

    def test_stale_and_slow_confirmation_rejected(self):
        now=datetime.now(timezone.utc)
        def book(start,end):return {'requestStartedAt':start.isoformat(),'receivedAt':end.isoformat()}
        self.assertFalse(recent({'a':book(now-timedelta(seconds=40),now)},30,5,now))
        self.assertFalse(recent({'a':book(now-timedelta(seconds=6),now)},30,5,now))
        self.assertTrue(recent({'a':book(now-timedelta(seconds=2),now)},30,5,now))

    def test_partial_data_is_unknown_then_full_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            history=History(Path(directory)/'history.sqlite3')
            c=candidates(fixture(),0)[0]
            self.assertEqual(len(history.transition({c['id']:{'state':'confirmed','candidate':c}}, {'1','2'},1,.005)),1)
            self.assertEqual(history.transition({c['id']:{'state':'confirmed','candidate':c}}, {'1','2'},1,.005),[])
            events=history.transition({}, {'1'},1,.005)
            self.assertEqual(events[0]['state'],'unknown')
            events=history.transition({}, {'1','2'},1,.005)
            self.assertEqual(events[0]['state'],'cleared')
            history.db.close()

    def test_threshold_and_restart_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'h.sqlite3';h=History(path)
            c=candidates(fixture(),0)[0]
            h.transition({c['id']:{'state':'confirmed','candidate':c}}, {'1','2'},101,.005)
            self.assertEqual(h.states[c['id']]['state'],'below_threshold')
            h.db.close();h=History(path)
            self.assertEqual(len(h.states),1)
            h.db.close()

    def test_lock_prevents_second_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            self.assertFalse(running(path))
            with instance_lock(path):self.assertTrue(running(path))
            self.assertFalse(running(path))

    def monitor(self, directory, data):
        parser=argparse.ArgumentParser();options(parser)
        args=parser.parse_args(['--directory',directory,'--slug','test'])
        return Monitor(args,FakeClient(data))

    def test_full_cycle_and_current_depth_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=self.monitor(directory,fixture())
            monitor.cycle()
            status=json.loads((Path(directory)/'status.json').read_text())
            self.assertEqual(status['quotesRead'],2)
            self.assertEqual(status['confirmedCandidates'][0]['quantityEach'],1000)
            self.assertEqual(status['confirmedCandidates'][0]['tournamentStatus'],'draft')
            monitor.history.db.close()

    def test_opportunity_vanishes_on_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            data=fixture();monitor=self.monitor(directory,data)
            changed=json.loads(json.dumps(data['books']))
            for b in changed.values():b['bids']=[{'price':.3,'quantity':1000}];b['bestBid']=.3
            monitor.client.depth_override=changed
            monitor.cycle()
            self.assertEqual(monitor.status['confirmedCandidates'],[])
            self.assertEqual(list(monitor.history.states.values())[0]['state'],'cleared')
            monitor.history.db.close()

    def test_failed_depth_never_alerts_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=self.monitor(directory,fixture());monitor.client.failed_exchange='2'
            monitor.cycle()
            self.assertEqual(monitor.status['confirmedCandidates'],[])
            self.assertEqual(monitor.status['unknownCandidates'],1)
            monitor.history.db.close()

    def test_delta_expands_siblings_and_preserves_other_candidates(self):
        data=fixture()
        other=fixture()
        for m in other['markets']:
            old=m['id']; new=str(int(old)+2)
            m['id']=new; m['exchanges']=[{'id':new}]
            data['markets'].append(m)
            data['nodes'][new]=other['nodes'][old]
            data['nodes'][new]['root']['contract_details']['raceId']='other'
            data['books'][new]=dict(other['books'][old],exchangeId=new,marketId=new)
        with tempfile.TemporaryDirectory() as directory:
            monitor=self.monitor(directory,data)
            monitor.cycle()
            self.assertEqual(len(monitor.status['confirmedCandidates']),2)
            monitor.cycle({'1'})
            self.assertEqual(monitor.status['quotesRead'],2)
            self.assertEqual(monitor.status['exchanges'],4)
            self.assertEqual(len(monitor.status['confirmedCandidates']),2)
            self.assertEqual(monitor.affected_exchanges({'1'}),{'1','2'})
            monitor.history.db.close()

    def test_inflight_event_invalidates_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=self.monitor(directory,fixture())
            monitor.cycle(guard=lambda ids: False)
            self.assertEqual(monitor.status['confirmedCandidates'],[])
            self.assertEqual(monitor.status['unknownCandidates'],1)
            monitor.history.db.close()


if __name__=='__main__':unittest.main()
