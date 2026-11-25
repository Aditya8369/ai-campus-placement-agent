import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../../static/js/modules/analysis_lifecycle.js', import.meta.url), 'utf8');
const { createAnalysisRun } = await import(`data:text/javascript,${encodeURIComponent(source)}`);

function mockFetch(t, implementation = () => Promise.resolve({ ok: true })) {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = (...args) => { requests.push(args); return implementation(...args); };
  t.after(() => { globalThis.fetch = original; });
  return requests;
}

test('departure cancels the acknowledged task with a small same-origin keepalive request', t => {
  const requests = mockFetch(t);
  const run = createAnalysisRun();
  run.acknowledgeTask('task/with spaces');
  run.leave();
  assert.equal(run.signal.aborted, true);
  assert.equal(run.stopped, true);
  assert.equal(requests.length, 1);
  const [url, options] = requests[0];
  assert.equal(url, '/api/analysis/cancel/task%2Fwith%20spaces');
  assert.equal(options.keepalive, true);
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.method, 'POST');
  assert.deepEqual(JSON.parse(options.body), { task_id: 'task/with spaces' });
  assert.equal(options.signal, undefined, 'cancel request must survive the client abort');
});

test('repeated departure and acknowledgement cannot duplicate cancellation', t => {
  const requests = mockFetch(t);
  const run = createAnalysisRun();
  run.acknowledgeTask('task-1');
  run.leave(); run.leave(); run.acknowledgeTask('task-1');
  assert.equal(requests.length, 1);
});

test('completed tasks are not cancelled on navigation', t => {
  const requests = mockFetch(t);
  const run = createAnalysisRun();
  run.acknowledgeTask('finished'); run.finish();
  assert.equal(run.signal.aborted, true);
  run.leave();
  assert.equal(requests.length, 0);
});

test('pending start aborts without inventing a task ID; a late acknowledgement is cancelled', t => {
  const requests = mockFetch(t);
  const run = createAnalysisRun();
  run.leave();
  assert.equal(requests.length, 0);
  assert.equal(run.signal.aborted, true);
  run.acknowledgeTask(undefined);
  assert.equal(requests.length, 0);
  run.acknowledgeTask('late-task');
  assert.equal(requests.length, 1);
});

test('cancellation preserves the existing CSRF contract', t => {
  const requests = mockFetch(t);
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => ({ getAttribute: () => 'synthetic-csrf-token' }) };
  t.after(() => { globalThis.document = previous; });
  const run = createAnalysisRun();
  run.acknowledgeTask('owned-task'); run.leave();
  assert.equal(requests[0][1].headers['X-CSRFToken'], 'synthetic-csrf-token');
});

test('synchronous unload transport failure still aborts client work', t => {
  mockFetch(t, () => { throw new TypeError('keepalive unavailable'); });
  const run = createAnalysisRun();
  run.acknowledgeTask('task');
  assert.doesNotThrow(() => run.leave());
  assert.equal(run.signal.aborted, true);
});

test('rejected unload requests do not create unhandled rejections', async t => {
  mockFetch(t, () => Promise.reject(new Error('network unavailable')));
  const run = createAnalysisRun();
  run.acknowledgeTask('task'); run.leave();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(run.departed, true);
});

test('unsupported AbortController still permits cooperative task cancellation', t => {
  const requests = mockFetch(t);
  const previous = globalThis.AbortController;
  globalThis.AbortController = undefined;
  t.after(() => { globalThis.AbortController = previous; });
  const run = createAnalysisRun();
  assert.equal(run.signal, undefined);
  run.acknowledgeTask('task'); run.leave();
  assert.equal(requests.length, 1);
});

test('separate runs do not revive departed callbacks or cancel another task', t => {
  const requests = mockFetch(t);
  const oldRun = createAnalysisRun(); oldRun.acknowledgeTask('old'); oldRun.leave();
  const newRun = createAnalysisRun(); newRun.acknowledgeTask('new');
  assert.equal(oldRun.stopped, true);
  assert.equal(newRun.stopped, false);
  newRun.finish(); newRun.leave();
  assert.equal(requests.length, 1);
});
