// Private, receive-only tournament subscription. stdout is a JSON-lines pipe.
// API keys and minted tokens are never included in messages or logs.
import { readFileSync } from 'node:fs';
import { createClient } from '@supabase/supabase-js';

const tournamentId = process.argv[2];
if (!/^[a-f0-9-]{36}$/i.test(tournamentId ?? '')) process.exit(2);
let apiKey = process.env.SUPERMARKET_API_KEY;
if (!apiKey) {
  const line = readFileSync(new URL('../.env', import.meta.url), 'utf8')
    .split(/\r?\n/).find(x => x.startsWith('SUPERMARKET_API_KEY='));
  apiKey = line?.slice('SUPERMARKET_API_KEY='.length).trim().replace(/^["']|["']$/g, '');
}
if (!apiKey) process.exit(2);

let stopping = false;
let activeClient;
let generation = 0;
const emit = message => {
  if (!stopping) process.stdout.write(JSON.stringify({ ...message, bridgeAt: new Date().toISOString() }) + '\n');
};
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function shutdown() {
  if (stopping) return;
  stopping = true;
  const deadline = setTimeout(() => process.exit(0), 1500);
  deadline.unref();
  if (activeClient) await activeClient.removeAllChannels().catch(() => {});
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
process.stdin.resume();
process.stdin.on('end', shutdown); // Don't leave an orphan connection if Python dies.
process.stdout.on('error', shutdown);

async function mint() {
  // Authentication only. There are no order placement/cancellation calls.
  const response = await fetch('https://sig.thesuper.market/api/v1/realtime/token', {
    method: 'POST', headers: { Authorization: `Bearer ${apiKey}` }, signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`token_http_${response.status}`);
  const token = await response.json();
  const url = new URL(token.supabaseUrl);
  if (url.protocol !== 'https:' || !token.token || !token.anonKey || !token.channels?.user)
    throw new Error('invalid_token_response');
  if (!(Date.parse(token.expiresAt) > Date.now() + 60000)) throw new Error('invalid_token_expiry');
  return token;
}

function compact(event, payload) {
  if (event === 'violation') {
    return { tournamentId: payload.tournamentId, observedPrices: payload.observedPrices,
      computedAt: payload.computedAt, relationshipId: payload.relationshipId };
  }
  const result = { delivery: payload.delivery };
  for (const name of ['trades', 'bookDirty', 'marketSettled', 'fills', 'orderUpdates', 'settlements', 'refunds', 'collateralChanges']) {
    if (payload[name] !== undefined) result[name] = payload[name].map(x => ({
      exchangeId: x.exchangeId, marketId: x.marketId, tournamentId: x.tournamentId,
      at: x.at ?? x.executedAt,
    }));
  }
  return result;
}

let failures = 0;
while (!stopping) {
  let client;
  let healthTimer;
  let refreshTimer;
  let joinDeadline;
  const thisGeneration = ++generation;
  try {
    emit({ kind: 'reset', reason: failures ? 'connection_recovery' : 'initial_or_token_refresh' });
    const token = await mint();
    const subscriptions = new Map();
    client = createClient(token.supabaseUrl, token.anonKey, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      realtime: {
        heartbeatIntervalMs: 10000, timeout: 10000, logger: () => {},
        heartbeatCallback: (status, latency) => {
          if (thisGeneration !== generation) return;
          emit({ kind: 'heartbeat', status, latencyMs: latency ?? null });
        },
      },
    });
    activeClient = client;
    await client.realtime.setAuth(token.token);
    let previouslyReady = false;
    let lastTransport = false;
    const channels = [
      [`tournament:${tournamentId}`, 'market_batch'],
      [`relationships:violations:${tournamentId}`, 'violation'],
      [token.channels.user, 'account_batch'],
    ];
    const session = new Promise((resolve, reject) => {
      refreshTimer = setTimeout(() => resolve(), Date.parse(token.expiresAt) - Date.now() - 60000);
      joinDeadline = setTimeout(() => reject(new Error('subscription_timeout')), 30000);
      for (const [topic, event] of channels) {
        subscriptions.set(topic, 'JOINING');
        client.channel(topic, { config: { private: true } })
          .on('broadcast', { event }, ({ payload }) => {
            if (thisGeneration !== generation) return;
            try { emit({ kind: 'batch', topic, event, payload: compact(event, payload) }); }
            catch { emit({ kind: 'reset', reason: 'malformed_batch' }); }
          })
          .subscribe(status => {
            if (thisGeneration !== generation) return;
            subscriptions.set(topic, status);
            emit({ kind: 'subscription', topic, status });
            const ready = [...subscriptions.values()].every(x => x === 'SUBSCRIBED') && subscriptions.size === 3;
            if (ready) {
              clearTimeout(joinDeadline);
              joinDeadline = undefined;
              if (!previouslyReady) {
                failures = 0;
                emit({ kind: 'ready', channels: channels.map(x => x[0]), expiresAt: token.expiresAt });
              }
            } else if (!joinDeadline) {
              // A channel can fail hours after joining. Local health messages
              // do not prove subscription health; bound SDK rejoin attempts.
              joinDeadline = setTimeout(() => reject(new Error('subscription_timeout')), 30000);
            }
            previouslyReady = ready;
          });
      }
      healthTimer = setInterval(() => {
        const connected = client.realtime.isConnected();
        if (!connected && lastTransport) emit({ kind: 'reset', reason: 'socket_disconnected' });
        lastTransport = connected;
        emit({ kind: 'health', connected, subscribed: [...subscriptions.values()].filter(x => x === 'SUBSCRIBED').length });
      }, 2000);
    });
    await session;
  } catch (error) {
    // Only our predefined reason/status labels may cross the pipe.
    const allowed = /^(token_http_\d+|invalid_token_response|invalid_token_expiry|subscription_timeout)$/;
    emit({ kind: 'reset', reason: allowed.test(error.message) ? error.message : 'transport_or_token_error' });
    failures++;
  } finally {
    generation++;
    clearInterval(healthTimer);
    clearTimeout(refreshTimer);
    clearTimeout(joinDeadline);
    if (client) await client.removeAllChannels().catch(() => {});
    activeClient = undefined;
  }
  if (!stopping) await pause(failures ? Math.min(60000, 1000 * 2 ** Math.min(failures, 6)) : 100);
}
