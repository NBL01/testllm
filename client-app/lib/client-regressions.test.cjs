const assert = require('node:assert/strict');
const { test, afterEach } = require('node:test');
const ts = require('typescript');
const fs = require('node:fs');

require.extensions['.ts'] = (module, filename) => {
  const source = fs.readFileSync(filename, 'utf8');
  module._compile(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, filename);
};
const { requestJson, requestDownload } = require('./apiClient.ts');
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

test('FastAPI validation arrays include field locations', async () => {
  global.fetch = async () => new Response(JSON.stringify({ detail: [
    { loc: ['body', 'max_output_tokens'], msg: 'Must be at most 1024' }
  ] }), { status: 422 });
  await assert.rejects(requestJson('/evaluation-jobs'), error =>
    error.kind === 'validation_error' && /max_output_tokens: Must be at most 1024/.test(error.message));
});

test('plain text errors survive one-pass parsing', async () => {
  global.fetch = async () => new Response('Upstream connection unavailable', { status: 502 });
  await assert.rejects(requestJson('/health'), /Upstream connection unavailable/);
});

test('resource 404 is not called a missing endpoint', async () => {
  global.fetch = async () => new Response('{"detail":"Evaluation job missing"}', { status: 404 });
  await assert.rejects(requestJson('/evaluation-jobs/missing'), error => error.kind === 'resource_not_found');
});

test('optional missing models route remains identifiable', async () => {
  global.fetch = async () => new Response('{"detail":"Not Found"}', { status: 404 });
  await assert.rejects(requestJson('/models'), error => error.kind === 'endpoint_not_found');
});

test('malformed success produces an actionable API error', async () => {
  global.fetch = async () => new Response('<html>proxy failure</html>');
  await assert.rejects(requestJson('/health'), error => error.kind === 'invalid_response');
});

test('network failure mentions CORS', async () => {
  global.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(requestJson('/health'), /CORS/);
});

test('GET timeout includes stalled response bodies', async () => {
  global.fetch = async (_url, options) => ({
    ok: true,
    text: () => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason)))
  });
  await assert.rejects(requestJson('/health', { timeoutMs: 5 }), error => error.kind === 'request_timeout');
});

test('download helper receives complete server CSV, not a JSON page', async () => {
  const csv = 'case,answer\n' + 'example,safe\n'.repeat(5001);
  global.fetch = async url => {
    assert.match(url, /failed-cases\.csv$/);
    return new Response(csv, { headers: { 'Content-Type': 'text/csv' } });
  };
  const blob = await requestDownload('/evaluation-jobs/id/failed-cases.csv');
  assert.equal(await blob.text(), csv);
});

test('numeric validation rejects nonfinite, fractional counts and backend bounds', () => {
  const { validateJobNumbers } = require('./jobForm.ts');
  const valid = { repeat_count: 1, temperature: 0, max_output_tokens: 1024, timeout_seconds: 300, limit: 0 };
  assert.deepEqual(validateJobNumbers(valid), []);
  for (const [field, values] of Object.entries({
    repeat_count: [0, 1.5, NaN, Infinity], temperature: [-1, NaN, Infinity],
    max_output_tokens: [0, 1025, 1.5, NaN, Infinity], timeout_seconds: [4, 301, NaN, Infinity],
    limit: [-1, 1.5, NaN, Infinity]
  })) for (const value of values) assert.ok(validateJobNumbers({ ...valid, [field]: value }).length, `${field}=${value}`);
});

test('malformed catalog is rejected instead of rendering invented presets', () => {
  const { validateJobOptions } = require('./jobForm.ts');
  assert.throws(() => validateJobOptions({ providers: ['mock'] }), /catalog/);
});
