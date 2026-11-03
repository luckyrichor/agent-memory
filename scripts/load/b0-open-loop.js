// Record the actual installed k6 version in every execution manifest.
import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';

const requests = new SharedArray('frozen-b0-requests', () => JSON.parse(open(__ENV.B0_REQUESTS_PATH)));
const token = __ENV.B0_TOKEN_PATH ? open(__ENV.B0_TOKEN_PATH).trim() : '';
const rate = Number(__ENV.B0_RATE);
const schedule = {0.1: [1, '10s'], 0.25: [1, '4s'], 0.5: [1, '2s'], 1: [1, '1s']}[rate];
if (!schedule || requests.length === 0) throw new Error('Invalid frozen workload');
const loadServer = __ENV.B0_BASE_URL;
if (!loadServer || !loadServer.startsWith('https://')) throw new Error('Private authorized HTTPS endpoint required');
const measured = new Counter('b0_sample_requests');
const failed = new Counter('b0_sample_errors');
const clientMs = new Trend('b0_sample_client_ms', true);
const writeAck = new Counter('b0_write_confirmed');
const serverMs = new Trend('b0_sample_server_ms', true);
export const options = {
  scenarios: { sample: { executor: 'constant-arrival-rate', rate: schedule[0], timeUnit: schedule[1], duration: '6m', preAllocatedVUs: 20, maxVUs: 200, gracefulStop: '30s' } },
  discardResponseBodies: true,
  // No invented latency target before B0. Dropped arrivals invalidate a capacity claim.
  thresholds: { 'dropped_iterations{scenario:sample}': ['count==0'] }
};
function issue(observe) {
  const row = requests[exec.scenario.iterationInTest % requests.length];
  const res = http.request(row.method || 'POST', loadServer + row.path, JSON.stringify(row.body), {
    headers: { Authorization: 'Bearer ' + (row.token || token), 'Content-Type': 'application/json',
      ...(__ENV.B0_HOST ? { Host: __ENV.B0_HOST } : {}),
      ...(row.method === 'POST' && row.operation === 'write' ? {'Idempotency-Key': 'pf-'+exec.scenario.iterationInTest} : {}) },
    ...(row.operation === 'write' ? {responseType: 'text'} : {}),
    timeout: '30s', redirects: 0, tags: { operation: row.operation }
  });
  if (row.operation === 'write' && res.status === 201) {
    const value = res.json();
    writeAck.add(1);
    console.log('B0_ACK ' + JSON.stringify({memory_id: value.memory_id, version_id: value.version_id, measured: observe}));
  }
  if (observe) {
    measured.add(1);
    failed.add(res.status >= 400 || res.status === 0 ? 1 : 0);
    clientMs.add(res.timings.duration);
    const core = Number(res.headers['X-B0-Server-Ms']);
    if (res.headers['X-B0-Server-Ms'] !== undefined && Number.isFinite(core)) serverMs.add(core);
  }
}
export default function () { issue(Date.now() - exec.scenario.startTime >= 60000); }
