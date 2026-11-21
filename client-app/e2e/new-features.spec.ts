import { test, expect } from '@playwright/test';

// Browser coverage for UI that previously had only unit tests (written and run by an agy agent, 2026-11-21).
const api = 'http://127.0.0.1:18000';

test.beforeEach(async ({ page }) => {
  // Discovery is optional; never contact a developer's real Ollama daemon.
  await page.route(`${api}/models`, route => route.fulfill({
    status: 404, json: { detail: 'Not Found' }
  }));
});

test('failure triage chips filter failed attempts by error type and restore total', async ({ page, request }) => {
  const job = await (await request.post(`${api}/evaluation-jobs`, {
    data: {
      provider: 'mock',
      model_name: 'mock-failing',
      input_path: 'data/raw/llm_eval_dataset_v2_300.jsonl',
      dataset_version: 'v2.0-demo',
      evaluation_mode: 'exploratory',
      limit: 40
    }
  })).json();
  expect((await request.post(`${api}/evaluation-jobs/${job.job_id}/run?wait=true`)).ok()).toBeTruthy();

  await page.goto(`/jobs/${job.job_id}`);
  await expect(page.getByText('completed', { exact: true })).toBeVisible();

  const failedSection = page.locator('section').filter({ has: page.getByRole('heading', { name: /^Failed Attempts/ }) });
  const chipGroup = failedSection.getByRole('group', { name: 'Filter failed attempts' });
  await expect(chipGroup).toBeVisible();

  const allChip = chipGroup.getByRole('button', { name: /^All/ });
  await expect(allChip).toBeVisible();
  const allCount = await allChip.locator('.chip-count').innerText();
  await expect(failedSection.getByRole('heading', { name: `Failed Attempts (${allCount})` })).toBeVisible();

  const errorChip = chipGroup.getByRole('button').filter({ hasNotText: /^All/ }).filter({ hasNotText: /^category:/ }).first();
  await expect(errorChip).toBeVisible();
  const chipCount = await errorChip.locator('.chip-count').innerText();
  const errorType = (await errorChip.evaluate(el => {
    const clone = el.cloneNode(true) as HTMLElement;
    clone.querySelector('.chip-count')?.remove();
    return clone.textContent?.trim();
  }))!;

  await errorChip.click();
  await expect(failedSection.getByRole('heading', { name: `Failed Attempts (${chipCount})` })).toBeVisible();

  const failureRows = failedSection.locator('.evidence-list details.evidence');
  await expect(failureRows.first()).toBeVisible();
  const count = await failureRows.count();
  expect(count).toBeGreaterThan(0);
  for (const row of await failureRows.all()) {
    await expect(row.locator('.pill.status-failed')).toHaveText(errorType);
  }

  await allChip.click();
  await expect(failedSection.getByRole('heading', { name: `Failed Attempts (${allCount})` })).toBeVisible();
});

test('comparable draft duplicates job with another model and opens comparison with source', async ({ page, request }) => {
  const sourceJob = await (await request.post(`${api}/evaluation-jobs`, {
    data: {
      provider: 'mock',
      model_name: 'mock-failing',
      input_path: 'sample_test_cases.jsonl',
      limit: 4
    }
  })).json();
  expect((await request.post(`${api}/evaluation-jobs/${sourceJob.job_id}/run?wait=true`)).ok()).toBeTruthy();

  await page.goto(`/jobs/${sourceJob.job_id}`);
  await expect(page.getByText('completed', { exact: true })).toBeVisible();

  const details = page.locator('details.notes', { hasText: 'Run the same evaluation with another model' });
  await details.locator('summary').click();
  await details.getByLabel('Provider').selectOption('mock');
  await details.getByLabel('Model').fill('mock-baseline');

  await details.getByRole('button', { name: 'Create Comparable Draft', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/jobs/(?!${sourceJob.job_id})[0-9a-f-]+$`));
  const newJobId = page.url().split('/jobs/')[1].split(/[?#]/)[0];

  await expect(page.getByText('draft', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Run Evaluation', exact: true }).click();
  await expect(page.getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 });

  await page.getByRole('link', { name: 'Compare with Source', exact: true }).click();
  await expect(page).toHaveURL(`/compare?baseline=${sourceJob.job_id}&candidate=${newJobId}`);
  await expect(page.getByText('comparable', { exact: true })).toBeVisible();
});

test('compare URL state updates on swap and shows error for unknown job', async ({ page, request }) => {
  const runJob = async (model_name: string) => {
    const job = await (await request.post(`${api}/evaluation-jobs`, {
      data: { provider: 'mock', model_name, input_path: 'sample_test_cases.jsonl', limit: 4 }
    })).json();
    expect((await request.post(`${api}/evaluation-jobs/${job.job_id}/run?wait=true`)).ok()).toBeTruthy();
    return job.job_id as string;
  };

  const jobA = await runJob('mock-failing');
  const jobB = await runJob('mock-baseline');

  await page.goto(`/compare?baseline=${jobA}&candidate=${jobB}`);
  const baselinePicker = page.locator('label').filter({ hasText: /^Baseline/ }).locator('select');
  const candidatePicker = page.locator('label').filter({ hasText: /^Candidate/ }).locator('select');

  await expect(baselinePicker).toHaveValue(jobA);
  await expect(candidatePicker).toHaveValue(jobB);
  const labelB = await candidatePicker.locator('option:checked').innerText();

  await page.getByRole('button', { name: 'Swap', exact: true }).click();
  await expect(page).toHaveURL(`/compare?baseline=${jobB}&candidate=${jobA}`);
  await expect(baselinePicker).toHaveValue(jobB);
  await expect(baselinePicker.locator('option:checked')).toHaveText(labelB);

  const unknownId = 'unknown-id-999999';
  await page.goto(`/compare?baseline=${unknownId}&candidate=${jobB}`);
  await expect(page.getByText(`Job ${unknownId} was not found or has no completed run.`)).toBeVisible();
});

test('no horizontal overflow on completed job page and compare result page', async ({ page, request }) => {
  const runJob = async (model_name: string) => {
    const job = await (await request.post(`${api}/evaluation-jobs`, {
      data: { provider: 'mock', model_name, input_path: 'sample_test_cases.jsonl', limit: 4 }
    })).json();
    expect((await request.post(`${api}/evaluation-jobs/${job.job_id}/run?wait=true`)).ok()).toBeTruthy();
    return job.job_id as string;
  };

  const jobA = await runJob('mock-failing');
  const jobB = await runJob('mock-baseline');

  await page.goto(`/jobs/${jobA}`);
  await expect(page.getByText('completed', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);

  await page.goto(`/compare?baseline=${jobA}&candidate=${jobB}`);
  await expect(page.getByText('comparable', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
