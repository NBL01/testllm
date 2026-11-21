import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const api = 'http://127.0.0.1:18000';

test.beforeEach(async ({ page }) => {
  // Discovery is optional; never contact a developer's real Ollama daemon.
  await page.route(`${api}/models`, route => route.fulfill({
    status: 404, json: { detail: 'Not Found' }
  }));
});

async function openDraft(page: Page) {
  await page.goto('/jobs/new');
  await expect(page.getByRole('heading', { name: 'Create Evaluation Job' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create Draft Job', exact: true })).toBeEnabled();
  await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption('mock');
  await page.getByRole('combobox', { name: 'Model name', exact: true }).selectOption('mock-failing');
  await page.getByRole('combobox', { name: 'Dataset preset', exact: true }).selectOption('sample_test_cases.jsonl');
  await page.getByLabel('Test-case limit', { exact: false }).fill('3');
}

test('mock preset draft runs against FastAPI and exposes evidence and exports', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openDraft(page);
  const createdResponse = page.waitForResponse(response => response.url() === `${api}/evaluation-jobs`
    && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create Draft Job', exact: true }).click();
  const response = await createdResponse;
  expect(response.status()).toBe(201);
  const created = await response.json();
  expect(created).toMatchObject({ status: 'draft', provider: 'mock', model_name: 'mock-failing',
    input_path: 'data/raw/sample_test_cases.jsonl', linked_run_id: null });
  await expect(page.getByText('Draft evaluation job created.', { exact: true })).toBeVisible();
  await page.locator(`a[href="/jobs/${created.job_id}"]`).click();
  await expect(page.getByText('draft', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Run Evaluation', exact: true }).click();
  await expect(page.getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('heading', { name: 'Summary Metrics' })).toBeVisible();

  const summaryResponse = await request.get(`${api}/evaluation-jobs/${created.job_id}/summary`);
  expect(summaryResponse.ok()).toBeTruthy();
  const summary = await summaryResponse.json();
  expect(summary.report.total_test_cases).toBe(3);
  expect(summary.report.failed).toBeGreaterThan(0);
  const runId: string = summary.job.linked_run_id;
  expect(runId).toBeTruthy();
  expect(summary.report.run_id).toBe(runId);
  const failures = page.locator('section').filter({ has: page.getByRole('heading', { name: /^Failed Attempts/ }) });
  const failure = failures.locator('details').first();
  await expect(failure).toBeVisible();
  const caseId = await failure.locator('summary strong').innerText();
  await failure.locator('summary').click();
  await expect(failure.getByText('Expected answer', { exact: true })).toBeVisible();
  await expect(failure.getByText('Actual answer', { exact: true })).toBeVisible();
  await failure.getByRole('link', { name: /View Case Traces/ }).click();
  await expect(page.getByLabel('Filter case')).toHaveValue(caseId);
  const traces = page.locator('section').filter({ has: page.getByRole('heading', { name: /^Oracle Traces/ }) });
  await expect(traces.locator('details').first()).toBeVisible();
  await expect(traces.locator('details summary strong').first()).toHaveText(caseId);
  await traces.locator('details summary').first().click();
  await expect(traces.getByText('Effective oracle configuration', { exact: true }).first()).toBeVisible();

  for (const [name, extension] of [['Download .md', '.md'], ['Download Client .json (sample)', '.json'],
    ['Download All Failed Attempts .csv', '.csv']]) {
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name, exact: true }).click();
    const download = await downloading;
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\${extension}$`));
    const filename = await download.path();
    expect(filename).not.toBeNull();
    const body = await readFile(filename!, 'utf8');
    expect(body.length).toBeGreaterThan(30);
    if (extension === '.json') expect(JSON.parse(body).run_id).toBe(runId);
    if (extension === '.csv') expect(body).toContain(caseId);
    if (extension === '.md') expect(body).toContain(runId);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  const retryResponse = page.waitForResponse(response => response.url() === `${api}/evaluation-jobs/${created.job_id}/retry`);
  await page.getByRole('button', { name: 'Retry + Queue New Job', exact: true }).click();
  const retry = await (await retryResponse).json();
  expect(retry).toMatchObject({ source_job_id: created.job_id, status: 'queued', dataset_sha256: created.dataset_sha256 });
  await expect(page).toHaveURL(`/jobs/${retry.job_id}`);
  await page.getByRole('button', { name: 'Run This Queued Job', exact: true }).click();
  await expect(page.getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 });
  expect(errors).toEqual([]);
});

test('every enabled preset executes its displayed dataset and mode', async ({ page, request }) => {
  const options = await (await request.get(`${api}/evaluation-jobs/options`)).json();
  expect(options.datasets.length).toBeGreaterThan(0);
  for (const dataset of options.datasets) {
    await openDraft(page);
    await page.getByRole('combobox', { name: 'Dataset preset', exact: true }).selectOption(dataset.id);
    await expect(page.getByRole('combobox', { name: 'Evaluation mode', exact: true })).toHaveValue(dataset.evaluation_mode);
    await expect(page.getByText('Effective dataset:', { exact: false })).toContainText(dataset.input_path);
    const createdResponse = page.waitForResponse(response => response.url() === `${api}/evaluation-jobs`
      && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create Draft Job', exact: true }).click();
    const created = await (await createdResponse).json();
    expect(created).toMatchObject({ input_path: dataset.input_path, dataset_version: dataset.dataset_version,
      evaluation_mode: dataset.evaluation_mode });
    await page.getByRole('link', { name: 'View Job', exact: true }).click();
    await page.getByRole('button', { name: 'Run Evaluation', exact: true }).click();
    await expect(page.getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 });
  }
});

test('cancel dismissal and rapid repeated submission preserve a single draft', async ({ page, request }) => {
  await openDraft(page);
  let submissions = 0;
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route(`${api}/evaluation-jobs`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submissions++;
    await held;
    await route.continue();
  });
  const createdResponse = page.waitForResponse(response => response.url() === `${api}/evaluation-jobs`
    && response.request().method() === 'POST');
  await page.locator('form').evaluate(form => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await expect.poll(() => submissions).toBe(1);
  await expect(page.getByRole('combobox', { name: 'Model name', exact: true })).toBeDisabled();
  release();
  const created = await (await createdResponse).json();
  await page.getByRole('link', { name: 'View Job', exact: true }).click();
  let cancellations = 0;
  page.on('request', request => { if (request.url().endsWith('/cancel')) cancellations++; });
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Cancel Job', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run Evaluation', exact: true })).toBeEnabled();
  expect(cancellations).toBe(0);
  expect(submissions).toBe(1);
  expect((await (await request.get(`${api}/evaluation-jobs/${created.job_id}`)).json()).status).toBe('draft');
});

test('both local provider names disclose missing models', async ({ page }) => {
  await page.route(`${api}/models`, route => route.fulfill({ json: {
    provider: 'ollama', ollama_reachable: false, installed_models: [], recommended_models: [],
    available_models: [], error: 'Ollama offline'
  } }));
  await openDraft(page);
  for (const provider of ['ollama', 'local']) {
    await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption(provider);
    await expect(page.getByText('Selected Ollama model may not be installed locally.', { exact: false })).toBeVisible();
  }
});

test('missing models does not block mock creation and status can be rechecked', async ({ page }) => {
  await openDraft(page);
  const status = page.locator('section').filter({ has: page.getByRole('heading', { name: 'System Status' }) });
  await expect(status).toContainText('not checked');
  await page.route(`${api}/health`, route => route.abort('connectionrefused'));
  await page.getByRole('button', { name: 'Recheck Status and Options' }).click();
  await expect(status).toContainText('unreachable');
  await page.unroute(`${api}/health`);
  await page.getByRole('button', { name: 'Recheck Status and Options' }).click();
  await expect(status.getByText('ok', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create Draft Job', exact: true })).toBeEnabled();
});

for (const scenario of [
  { name: 'network/CORS', status: 0, title: 'Backend API unreachable', detail: 'CORS' },
  { name: 'missing endpoint', status: 404, title: 'API endpoint not found', detail: 'Not Found' },
  { name: 'validation', status: 422, title: 'Validation failed', detail: 'repeat_count' },
  { name: 'server error', status: 503, title: 'Backend request failed', detail: 'Smoke service unavailable' }
]) {
  test(`draft submission explains ${scenario.name} without losing input`, async ({ page }) => {
    await openDraft(page);
    await page.route(`${api}/evaluation-jobs`, route => {
      if (route.request().method() !== 'POST') return route.continue();
      if (!scenario.status) return route.abort('connectionrefused');
      if (scenario.status === 503) return route.fulfill({ status: 503, contentType: 'text/plain', body: scenario.detail });
      return route.fulfill({ status: scenario.status, json: { detail: scenario.status === 422
        ? [{ loc: ['body', 'repeat_count'], msg: 'Must be a positive integer', type: 'value_error' }]
        : scenario.detail } });
    });
    await page.getByRole('button', { name: 'Create Draft Job', exact: true }).click();
    await expect(page.getByText(scenario.title, { exact: true })).toBeVisible();
    await expect(page.locator('form')).toContainText(scenario.detail);
    await expect(page.getByRole('combobox', { name: 'Model name', exact: true })).toHaveValue('mock-failing');
    await expect(page.getByRole('button', { name: 'Create Draft Job', exact: true })).toBeEnabled();
  });
}

test('keyboard navigation reaches labeled form controls without horizontal overflow', async ({ page }) => {
  await openDraft(page);
  await page.getByRole('combobox', { name: 'Provider', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('combobox', { name: 'Model name', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('combobox', { name: 'Dataset source', exact: true })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  const back = page.getByRole('link', { name: 'Back to Jobs' });
  await back.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/jobs$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
