// k6 OSS v1.0.0. Private request corpus and token file are supplied on the load host.
import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';

const requests = new SharedArray('frozen-b0-requests', () => JSON.parse(open(__ENV.B0_REQUESTS_PATH)));
const token = open(__ENV.B0_TOKEN_PATH).trim();
const rate = Number(__ENV.B0_RATE);
if (!Number.isInteger(rate) || rate < 1 || requests.length === 0) throw new Error('Invalid frozen workload');
const loadServer = __ENV.B0_BASE_URL;
if (!loadServer || !loadServer.startsWith('https://')) throw new Error('Private authorized HTTPS endpoint required');
const measured = new Counter('b0_sample_requests');
const failed = new Counter('b0_sample_errors');
const clientMs = new Trend('b0_sample_client_ms', true);
export const options = {
  scenarios: { sample: { executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration: '6m', preAllocatedVUs: 20, maxVUs: 200, gracefulStop: '30s' } },
  discardResponseBodies: true,
  // No invented latency target before B0. Dropped arrivals invalidate a capacity claim.
  thresholds: { 'dropped_iterations{scenario:sample}': ['count==0'] }
};
function issue(observe) {
  const row = requests[exec.scenario.iterationInTest % requests.length];
  const res = http.request(row.method || 'POST', loadServer + row.path, JSON.stringify(row.body), {
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    timeout: '30s', redirects: 0, tags: { operation: row.operation }
  });
  if (observe) {
    measured.add(1);
    failed.add(res.status >= 500 || res.status === 0 ? 1 : 0);
    clientMs.add(res.timings.duration);
  }
}
export default function () { issue(Date.now() - exec.scenario.startTime >= 60000); }
