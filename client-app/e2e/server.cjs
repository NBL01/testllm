const { spawn } = require('node:child_process');
const { cpSync, existsSync, mkdtempSync, rmSync, symlinkSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const client = path.join(root, 'client-app');

function createBackendLaunch(env = process.env) {
  const directory = mkdtempSync(path.join(tmpdir(), 'reliability-e2e-'));
  return {
    directory,
    command: path.join(root, '.venv/bin/python'),
    args: ['-m', 'uvicorn', 'llm_reliability_analytics.main:app', '--app-dir', 'src',
      '--host', '127.0.0.1', '--port', '18000'],
    cwd: root,
    env: { ...env, LLM_RELIABILITY_DB_PATH: path.join(directory, 'test.duckdb'),
      LLM_RELIABILITY_CORS_ORIGINS: 'http://127.0.0.1:13000' },
    cleanup: () => rmSync(directory, { recursive: true, force: true })
  };
}

function createClientLaunch(env = process.env) {
  const directory = mkdtempSync(path.join(tmpdir(), 'reliability-next-e2e-'));
  try {
    // Never rebuild a teammate's .next or inherit their .env.local API URL.
    for (const name of ['app', 'lib', 'public', 'next.config.mjs', 'tsconfig.json',
      'next-env.d.ts', 'package.json', 'package-lock.json']) {
      if (existsSync(path.join(client, name))) cpSync(path.join(client, name), path.join(directory, name), { recursive: true });
    }
    symlinkSync(path.join(client, 'node_modules'), path.join(directory, 'node_modules'), 'dir');
  } catch (error) {
    rmSync(directory, { recursive: true, force: true });
    throw error;
  }
  return {
    directory,
    command: process.execPath,
    args: [path.join(client, 'node_modules/next/dist/bin/next'), 'start', '-H', '127.0.0.1', '-p', '13000'],
    cwd: directory,
    env: { ...env, NODE_ENV: 'production', NEXT_TELEMETRY_DISABLED: '1',
      NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:18000' },
    cleanup: () => rmSync(directory, { recursive: true, force: true })
  };
}

function serve(launch, buildFirst) {
  let child;
  let stopping = false;
  function start(command, args, onSuccess) {
    child = spawn(command, args, { cwd: launch.cwd, env: launch.env, stdio: 'inherit' });
    child.once('error', error => {
      console.error(error);
      launch.cleanup();
      process.exitCode = 1;
    });
    child.once('exit', (code, signal) => {
      if (!stopping && code === 0 && onSuccess) return onSuccess();
      launch.cleanup();
      process.exitCode = stopping ? 0 : code ?? (signal ? 1 : 0);
    });
  }
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    stopping = true;
    child?.kill(signal);
  });
  const startServer = () => start(launch.command, launch.args);
  if (buildFirst) start('npm', ['run', 'build'], startServer);
  else startServer();
}

module.exports = { createBackendLaunch, createClientLaunch };
if (require.main === module) {
  const isClient = process.argv[2] === 'client';
  serve(isClient ? createClientLaunch() : createBackendLaunch(), isClient);
}
