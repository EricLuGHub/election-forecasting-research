import unittest
from unittest.mock import Mock, patch

from research.realtime import FeedInbox, FeedBridge


def batch(revision, previous, eid='1', tournament='T'):
    return {'kind':'batch', 'topic':'tournament:T', 'event':'market_batch', 'payload':{
        'delivery':{'revision':revision, 'previousRevision':previous},
        'bookDirty':[{'exchangeId':eid, 'tournamentId':tournament}]}}


class FeedTests(unittest.TestCase):
    def ready(self):
        inbox=FeedInbox('T')
        inbox.accept({'kind':'ready'})
        ticket=inbox.take()
        inbox.reconcile(ticket,True)
        self.assertTrue(inbox.summary()['synchronized'])
        return inbox

    def test_first_batch_resync_then_targeted_updates(self):
        inbox=self.ready()
        inbox.accept(batch(1,None))
        first=inbox.take()
        self.assertTrue(first['full'])
        inbox.reconcile(first,True)
        inbox.accept(batch(2,1))
        ticket=inbox.take()
        self.assertFalse(ticket['full'])
        self.assertEqual(ticket['dirty'],{'1'})
        self.assertTrue(inbox.valid(ticket,{'1'}))
        inbox.accept(batch(3,2))
        self.assertFalse(inbox.valid(ticket,{'1'}))

    def test_duplicate_ignored_and_gap_invalidates(self):
        inbox=self.ready()
        inbox.accept(batch(1,None)); ticket=inbox.take(); inbox.reconcile(ticket,True)
        inbox.accept(batch(1,None))
        self.assertFalse(inbox.wake.is_set())
        self.assertEqual(inbox.summary()['duplicateBatches'],1)
        inbox.accept(batch(3,2))
        self.assertFalse(inbox.summary()['synchronized'])
        self.assertEqual(inbox.summary()['revisionGaps'],1)
        self.assertFalse(inbox.valid(ticket,{'1'}))
        self.assertTrue(inbox.take()['full'])

    def test_reconnect_cannot_be_reconciled_by_old_scan(self):
        inbox=self.ready(); ticket=inbox.take(periodic=True)
        inbox.accept({'kind':'reset','reason':'socket_disconnected'})
        inbox.accept({'kind':'ready'})
        inbox.reconcile(ticket,True)
        self.assertFalse(inbox.summary()['synchronized'])
        inbox.reconcile(inbox.take(),True)
        self.assertTrue(inbox.summary()['synchronized'])

    def test_foreign_tournament_and_settlement(self):
        inbox=self.ready(); inbox.accept(batch(1,None,tournament='other'))
        self.assertEqual(inbox.take()['dirty'],set())
        message=batch(2,1)
        message['payload']['marketSettled']=[{'marketId':'M','tournamentId':'T'}]
        inbox.accept(message)
        ticket=inbox.take()
        self.assertTrue(ticket['catalogDirty'])
        self.assertTrue(ticket['full'])

    def test_failure_schedules_full_retry(self):
        inbox=self.ready(); ticket=inbox.take()
        inbox.reconcile(ticket,False)
        self.assertFalse(inbox.summary()['synchronized'])
        self.assertTrue(inbox.wake.is_set())
        self.assertTrue(inbox.take()['full'])

    def test_health_messages_do_not_extend_disconnection_deadline(self):
        with patch('research.realtime.time.monotonic', return_value=100):
            inbox = self.ready()
            inbox.accept({'kind': 'subscription', 'status': 'CHANNEL_ERROR'})
        with patch('research.realtime.time.monotonic', return_value=200):
            inbox.accept({'kind': 'health', 'connected': True})
            inbox.accept({'kind': 'subscription', 'status': 'CHANNEL_ERROR'})
            health = inbox.summary()
            self.assertFalse(health['connected'])
            self.assertEqual(health['secondsSinceBridgeMessage'], 0)
            self.assertEqual(health['secondsDisconnected'], 100)

    def test_watchdog_restarts_chatty_but_unsubscribed_child(self):
        with patch('research.realtime.time.monotonic', return_value=100):
            inbox = FeedInbox('T')
        bridge = FeedBridge.__new__(FeedBridge)
        bridge.inbox, bridge.process = inbox, Mock()
        bridge.process.poll.return_value = None
        with patch('research.realtime.time.monotonic', return_value=200):
            inbox.accept({'kind': 'health', 'connected': True})
            bridge.check_health()
            bridge.process.kill.assert_called_once()
            self.assertEqual(inbox.summary()['recoveryReason'], 'subscription_watchdog')
            self.assertEqual(inbox.summary()['secondsDisconnected'], 0)
            bridge.check_health()
            bridge.process.kill.assert_called_once()

    def test_ready_clears_disconnection_timer_but_needs_reconciliation(self):
        with patch('research.realtime.time.monotonic', return_value=100):
            inbox = FeedInbox('T')
        with patch('research.realtime.time.monotonic', return_value=500):
            inbox.accept({'kind': 'ready'})
            self.assertEqual(inbox.summary()['secondsDisconnected'], 0)
            self.assertTrue(inbox.summary()['connected'])
            self.assertFalse(inbox.summary()['synchronized'])


if __name__=='__main__':
    unittest.main()
