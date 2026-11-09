// SLO validation load test. The thresholds ARE the SLOs: the run fails if they are breached.
//   k6 run -e BASE_URL=https://files.example.com -e USERNAME=user -e PASSWORD=... \
//     -e FILE_ID=file-aaaa1111 loadtest/k6-slo.js
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    steady_6k: {
      executor: 'constant-arrival-rate',
      rate: 6000, timeUnit: '1s', duration: '10m',
      preAllocatedVUs: 800, maxVUs: 3000,
    },
  },
  thresholds: {
    'http_req_failed': ['rate<0.001'],
    'http_req_duration': ['p(99.9)<300'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'p(99.9)', 'max'],
};

export function setup() {
  const response = http.post(
    `${__ENV.BASE_URL}/auth/login`,
    JSON.stringify({ username: __ENV.USERNAME, password: __ENV.PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(response, { 'login succeeded': (res) => res.status === 200 });
  return response.cookies.fs_session[0].value;
}

export default function (session) {
  const response = http.get(`${__ENV.BASE_URL}/v1/files/${__ENV.FILE_ID}`, {
    headers: { Cookie: `fs_session=${session}` },
    tags: { name: 'metadata' },
  });
  check(response, { 'status 200': (res) => res.status === 200 });
}
