const assert = require('node:assert/strict');
const { test } = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const pkg = require('../package.json');

test('release scripts expose unit, browser and build gates', () => {
  assert.equal(pkg.scripts['test:unit'], 'node --test lib/*.test.cjs');
  assert.equal(pkg.scripts['test:e2e'], 'playwright test');
  assert.equal(pkg.scripts.build, 'next build');
});

test('production build fetches no remote fonts', () => {
  // next/font/google downloads at build time; offline or flaky networks then fail the release build.
  const layout = fs.readFileSync(path.join(__dirname, '../app/layout.tsx'), 'utf8');
  assert.doesNotMatch(layout, /next\/font\/google/);
});

test('backend launch always overrides inherited database and CORS settings', () => {
  const { createBackendLaunch } = require('./server.cjs');
  const launch = createBackendLaunch({
    LLM_RELIABILITY_DB_PATH: '/production/never-touch.duckdb',
    LLM_RELIABILITY_CORS_ORIGINS: 'https://production.invalid'
  });
  try {
    assert.equal(launch.command, path.resolve(__dirname, '../../.venv/bin/python'));
    assert.deepEqual(launch.args, ['-m', 'uvicorn', 'llm_reliability_analytics.main:app',
      '--app-dir', 'src', '--host', '127.0.0.1', '--port', '18000']);
    assert.equal(launch.cwd, path.resolve(__dirname, '../..'));
    assert.equal(launch.env.LLM_RELIABILITY_CORS_ORIGINS, 'http://127.0.0.1:13000');
    assert.ok(launch.directory.startsWith(path.join(os.tmpdir(), 'reliability-e2e-')));
    assert.equal(launch.env.LLM_RELIABILITY_DB_PATH, path.join(launch.directory, 'test.duckdb'));
    assert.equal(fs.existsSync(launch.env.LLM_RELIABILITY_DB_PATH), false);
  } finally {
    launch.cleanup();
  }
  assert.equal(fs.existsSync(launch.directory), false);
});
