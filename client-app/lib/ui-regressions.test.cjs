const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function loadSource(relative, mocks = {}) {
  const filename = path.resolve(__dirname, relative);
  const module = new Module(filename, moduleParent);
  module.filename = filename;
  module.paths = Module._nodeModulePaths(path.dirname(filename));
  const originalRequire = module.require.bind(module);
  module.require = name => {
    if (Object.hasOwn(mocks, name)) return mocks[name];
    if (name.startsWith('@/lib/')) return loadSource(`./${name.slice(6)}.ts`, mocks);
    return originalRequire(name);
  };
  module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  }).outputText, filename);
  return module.exports;
}
const moduleParent = module;
const job = {
  job_id: 'job-1', status: 'completed', linked_run_id: 'run-1', provider: 'mock', model_name: 'mock-baseline',
  input_path: 'data/raw/sample_test_cases.jsonl', dataset_version: 'v1', evaluation_mode: 'regression',
  oracle_profile: 'default', created_at: null, started_at: null, completed_at: null, updated_at: null,
  repeat_count: 2, temperature: 0, max_output_tokens: 128, limit: null
};
const report = {
  total_test_cases: 6, unique_test_cases: 3, passed: 4, failed: 2, accuracy: 2 / 3,
  average_latency_ms: 12, overall_reliability_score: 0.7, metric_version: 'legacy-v1',
  repeated_case_count: 3, schema_case_count: 1, measurement_notes: ['Scope is limited to dataset oracle checks.'],
  latency_sources: { mock_simulated: 4, observed: 2 },
  category_reports: [{ category: 'math', total_test_cases: 4, passed: 4, failed: 0, accuracy: 1 },
    { category: 'safety', total_test_cases: 2, passed: 0, failed: 2, accuracy: 0 }],
  error_distribution: { wrong_answer: 2 },
  repeat_k: 2, pass_at_k: 1, pass_hat_k: 0.5, p50_latency_ms: 10, p95_latency_ms: 20
};

function renderDetail(reportPayload, failures = {}, jobPatch = {}) {
  const current = { ...job, ...jobPatch };
  const { default: Page } = loadSource('../app/jobs/[jobId]/page.tsx', {
    '@/lib/api': {}, '@/lib/apiClient': {},
    'next/link': { default: props => React.createElement('a', props) },
    'next/navigation': { useRouter: () => ({ push() {} }), useParams: () => ({ jobId: 'job-1' }) },
    '@/lib/useRemoteResource': { useRemoteResource: key => ({
      loading: false, error: key?.endsWith(':report') ? failures.report || '' : '',
      data: key === 'job-1' ? current : key?.endsWith(':summary') ? { job: current, report: reportPayload } : null
    }) }
  });
  return renderToStaticMarkup(React.createElement(Page, { params: { jobId: 'job-1' } }));
}

test('detail route reads the active client parameter without synchronous page props', () => {
  const { default: Page } = loadSource('../app/jobs/[jobId]/page.tsx', {
    '@/lib/api': {}, '@/lib/apiClient': {},
    'next/navigation': { useParams: () => ({ jobId: 'active-job' }) }
  });
  const detail = Page();
  assert.equal(detail.key, 'active-job');
  assert.equal(detail.props.jobId, 'active-job');
});

test('detail renders backend unique_test_cases and latency source count dictionary', () => {
  const html = renderDetail(report);
  assert.match(html, /Unique cases<\/div><div class="kpi-value">3<\/div>/);
  assert.match(html, /mock_simulated: 4/);
  assert.match(html, /observed: 2/);
  assert.match(html, /3 repeated cases eligible/);
  assert.match(html, /1 schema cases eligible/);
  assert.match(html, /Scope is limited to dataset oracle checks/);
  assert.match(html, /2x repeat · temp 0 · 128 tokens/);
  assert.match(html, /Run the same evaluation with another model/);
  assert.match(html, />Create Comparable Draft<\/button>/);
  assert.match(html, /pass\^2<\/div><div class="kpi-value">50.0%/);
  assert.match(html, /pass@2<\/div><div class="kpi-value">100.0%/);
  assert.match(html, /Legacy composite \(legacy-v1\): <code>0.700/);
  // Failure triage chips: one per error type and per failing category, with counts.
  assert.match(html, /aria-label="Filter failed attempts"/);
  assert.match(html, />wrong_answer<span class="chip-count">2<\/span>/);
  assert.match(html, />category: safety<span class="chip-count">2<\/span>/);
  assert.doesNotMatch(html, /category: math</);
  // Weakest category first; a failure share is not a pass rate, so it gets the neutral tone.
  assert.ok(html.indexOf('<span>safety</span>') < html.indexOf('<span>math</span>'));
  assert.match(html, /tone-low" style="width:0%"/);
  assert.match(html, /tone-neutral" style="width:100%"/);
});

test('running job shows live progress and can be stopped; stop requests are announced', () => {
  const running = renderDetail(report, {}, { status: 'running', progress_done: 3, progress_total: 10 });
  assert.match(running, /3 of 10 attempts \(30%\)/);
  assert.match(running, /role="progressbar"[^>]*aria-valuemax="10" aria-valuenow="3"/);
  assert.match(running, />Stop Run<\/button>/);
  // Evidence is written when the run ends: no summary request (and no 'not found' error) while running.
  assert.match(running, /<h2>Summary Metrics<\/h2><p class="meta">Evaluation is in progress/);
  assert.doesNotMatch(running, /class="kpi-grid"/);
  const stopping = renderDetail(report, {}, { status: 'running', progress_done: 3, progress_total: 10, stop_requested: true });
  assert.match(stopping, /Stopping after the current attempt/);
  assert.doesNotMatch(stopping, />Stop Run</);
});

test('job list shows run outcomes, queue count and only recorded owner metadata', () => {
  const { default: Page } = loadSource('../app/jobs/page.tsx', {
    'next/link': { default: props => React.createElement('a', props) },
    '@/lib/api': {},
    '@/lib/useRemoteResource': { useRemoteResource: key => key === 'queue-stats'
      ? { data: { total: 2, by_status: { draft: 1, queued: 0, running: 0, completed: 1, failed: 0, canceled: 0 } }, error: '', loading: false }
      : { data: { total: 2, items: [
        { ...job, job_id: 'done-0001-x', project_name: 'Support bot', attempts: 60, passed_attempts: 6,
          submitted_by: 'nbl', client_name: '', team_name: 'Evals' },
        { ...job, job_id: 'draft-002-y', status: 'draft', linked_run_id: null, project_name: '', attempts: null,
          passed_attempts: null, submitted_by: '', client_name: '', team_name: '' }
      ] }, error: '', loading: false } }
  });
  const html = renderToStaticMarkup(React.createElement(Page));
  assert.match(html, /<strong>10%<\/strong> <span class="meta">6\/60 passed<\/span>/);
  assert.match(html, /Not run/);
  assert.match(html, /nbl · Evals/);
  assert.match(html, /Job draft-00/);
  assert.match(html, /Run queued jobs \(0\)<\/button>/);
  assert.match(html, /aria-pressed="true" type="button">All<span class="chip-count">2<\/span>/);
});

test('zero eligible cases are not measured and markdown failure cannot hide metrics or CSV', () => {
  const html = renderDetail({ ...report, repeated_case_count: 0, schema_case_count: 0, latency_sources: {},
    repeat_k: null, pass_at_k: null, pass_hat_k: null }, { report: 'Report unavailable' });
  assert.match(html, /pass\^k<\/div><div class="kpi-value">N\/A<\/div><div class="kpi-sub">needs 2\+ attempts per case/);
  assert.match(html, /not measured \(no repeated cases\)/);
  assert.match(html, /not measured \(no schema cases\)/);
  assert.match(html, /Latency sources: not reported/);
  assert.match(html, /Report unavailable/);
  assert.match(html, /Download All Failed Attempts .csv/);
  assert.match(html, /Unique cases<\/div><div class="kpi-value">3<\/div>/);
});

// Deterministic hook lifecycle harness. Effects flush separately to expose the
// render-to-effect window; no browser or dependency installation is required.
function hookHarness() {
  const slots = [];
  let index = 0;
  let pending = [];
  return {
    hooks: {
      useState(initial) {
        const slot = index++;
        if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
        return [slots[slot], value => { slots[slot] = typeof value === 'function' ? value(slots[slot]) : value; }];
      },
      useRef(initial) {
        const slot = index++;
        if (!(slot in slots)) slots[slot] = { current: initial };
        return slots[slot];
      },
      useEffect(effect, deps) {
        const slot = index++;
        const prior = slots[slot];
        if (!prior || deps.some((value, i) => !Object.is(value, prior.deps[i]))) {
          pending.push(() => { prior?.cleanup?.(); slots[slot] = { deps, cleanup: effect() }; });
        }
      }
    },
    render(callback) { index = 0; return callback(); },
    flush() { const effects = pending; pending = []; effects.forEach(effect => effect()); },
    cleanup() { slots.forEach(slot => slot?.cleanup?.()); }
  };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('refresh immediately marks old status loading before effects flush', async () => {
  const harness = hookHarness();
  const { useRemoteResource } = loadSource('./useRemoteResource.ts', { react: harness.hooks });
  const first = deferred();
  const render = refresh => harness.render(() => useRemoteResource('job', () => first.promise, refresh));
  render(0); harness.flush(); first.resolve({ status: 'draft' }); await first.promise;
  assert.equal(render(0).loading, false);
  const refreshing = render(1);
  assert.equal(refreshing.loading, true);
  assert.equal(refreshing.data.status, 'draft');
  harness.cleanup();
});

test('late old query response cannot populate the current filter', async () => {
  const harness = hookHarness();
  const { useRemoteResource } = loadSource('./useRemoteResource.ts', { react: harness.hooks });
  const old = deferred(), current = deferred();
  const render = key => harness.render(() => useRemoteResource(key, () => key === 'old' ? old.promise : current.promise));
  render('old'); harness.flush(); render('current'); harness.flush();
  current.resolve('current rows'); await current.promise;
  old.resolve('stale rows'); await old.promise;
  assert.equal(render('current').data, 'current rows');
  harness.cleanup();
});

test('same-query pre-action response is discarded when refresh revision changes', async () => {
  const harness = hookHarness();
  const { useRemoteResource } = loadSource('./useRemoteResource.ts', { react: harness.hooks });
  const old = deferred(), current = deferred();
  const render = revision => harness.render(() => useRemoteResource('job', () => revision ? current.promise : old.promise, revision));
  render(0); harness.flush(); render(1);
  old.resolve({ status: 'draft' }); await old.promise;
  assert.equal(render(1).data, null);
  harness.flush(); current.resolve({ status: 'failed' }); await current.promise;
  assert.equal(render(1).data.status, 'failed');
  harness.cleanup();
});

function elements(root) {
  if (!root || typeof root !== 'object') return [];
  if (Array.isArray(root)) return root.flatMap(elements);
  return [root, ...elements(root.props?.children)];
}
function textOf(root) {
  if (typeof root === 'string' || typeof root === 'number') return String(root);
  if (Array.isArray(root)) return root.map(textOf).join('');
  return root?.props ? textOf(root.props.children) : '';
}
function detailHarness(api, status = 'draft') {
  const harness = hookHarness();
  const revisions = [];
  const { default: Page } = loadSource('../app/jobs/[jobId]/page.tsx', {
    react: harness.hooks, '@/lib/api': api, '@/lib/apiClient': {},
    'next/link': { default: () => null },
    'next/navigation': { useRouter: () => ({ push() {} }), useParams: () => ({ jobId: 'job-1' }) },
    '@/lib/useRemoteResource': { useRemoteResource: (key, load, refresh, pollMs) => {
      if (key === 'job-1') revisions.push({ refresh, pollMs });
      return { loading: false, error: '', data: key === 'job-1' ? { ...job, status, linked_run_id: null } : null };
    } }
  });
  const Component = Page({ params: { jobId: 'job-1' } }).type;
  const render = () => harness.render(() => Component({ jobId: 'job-1' }));
  const button = (tree, label) => elements(tree).find(element => element.type === 'button' && textOf(element) === label);
  return { ...harness, render, button, revisions };
}

test('dismissed cancellation sends no POST', () => {
  let canceled = 0;
  const harness = detailHarness({ cancelJob: () => { canceled++; } });
  const previous = global.window;
  global.window = { prompt: () => null };
  try { harness.button(harness.render(), 'Cancel Job').props.onClick(); }
  finally { global.window = previous; harness.cleanup(); }
  assert.equal(canceled, 0);
});

test('queued run targets its own endpoint, serializes actions, polls, and refreshes after failure', async () => {
  const run = deferred();
  let runs = 0, canceled = 0;
  const harness = detailHarness({
    runJob: id => { assert.equal(id, 'job-1'); runs++; return run.promise; },
    cancelJob: () => { canceled++; }
  }, 'queued');
  const tree = harness.render(); harness.flush();
  const button = harness.button(tree, 'Run This Queued Job');
  button.props.onClick(); button.props.onClick();
  harness.button(tree, 'Cancel Job').props.onClick();
  assert.equal(runs, 1); assert.equal(canceled, 0);
  const running = harness.render();
  assert.ok(harness.button(running, 'Run This Queued Job').props.disabled);
  assert.equal(harness.revisions.at(-1).pollMs, 3000);
  run.reject(new Error('Provider went offline'));
  await run.promise.catch(() => {});
  const failed = harness.render();
  assert.match(textOf(failed), /Provider went offline/);
  assert.equal(harness.revisions.at(-1).refresh, 1);
  harness.cleanup();
});

test('blank numeric input stays invalid rather than becoming zero', () => {
  const harness = hookHarness();
  const { default: Page } = loadSource('../app/jobs/new/page.tsx', {
    react: { ...harness.hooks, useMemo: calculate => calculate() },
    '@/lib/api': {}, '@/lib/apiClient': { API_BASE_URL: 'http://localhost:8000' },
    'next/link': { default: () => null }
  });
  const render = () => harness.render(Page);
  const findInput = (tree, label) => elements(elements(tree).find(element => element.type === 'label' && textOf(element).trim() === label))
    .find(element => element.type === 'input');
  for (const label of ['Repeat count', 'Temperature', 'Max output tokens', 'Timeout seconds', 'Test-case limit (0 = none)']) {
    findInput(render(), label).props.onChange({ target: { value: '', valueAsNumber: NaN } });
    const tree = render();
    assert.equal(findInput(tree, label).props.value, '');
    assert.ok(elements(tree).find(element => element.type === 'button' && element.props.type === 'submit').props.disabled);
  }
  harness.cleanup();
});

test('queue button reports how many queued jobs were started in the background', async () => {
  const harness = hookHarness();
  const scheduled = deferred();
  const { default: Page } = loadSource('../app/jobs/page.tsx', {
    react: harness.hooks, 'next/link': { default: () => null },
    '@/lib/api': { processQueue: () => scheduled.promise },
    '@/lib/useRemoteResource': { useRemoteResource: () => ({ data: null, error: '', loading: false }) }
  });
  const render = () => harness.render(Page);
  const tree = render(); harness.flush();
  elements(tree).find(element => element.type === 'button' && textOf(element).startsWith('Run queued')).props.onClick();
  scheduled.resolve({ requested_max_jobs: 10, scheduled_count: 2, job_ids: ['a', 'b'] });
  await scheduled.promise;
  assert.match(textOf(render()), /Started 2 queued jobs; they run one at a time/);
  harness.cleanup();
});
