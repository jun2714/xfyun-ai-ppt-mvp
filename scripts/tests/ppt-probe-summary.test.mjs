import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeProbe } from '../lib/ppt-probe-summary.mjs';
import { readOutlineFailure } from '../lib/ppt-outline-failure.mjs';

test('persisted outline failure explains a generic UI failure without leaking detail', async () => {
  const calls = [];
  const failure = await readOutlineFailure('http://localhost/api/v1/ppt', 'project-id', {
    fetchImpl: async (...args) => {
      calls.push(args);
      return { ok: true, json: async () => ({ generation_metadata: {
        outline_status: 'failed', outline_error: '幼教课堂大纲质检失败：reveal-slide-missing PRIVATE_LESSON',
      } }) };
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'http://localhost/api/v1/ppt/presentation/project-id');
  assert.equal(calls[0][1].method, 'GET');
  assert.ok(calls[0][1].signal instanceof AbortSignal);
  const summary = summarizeProbe({ fatalError: {message: 'Outline UI reported failure.'}, outlineFailure: failure });
  assert.equal(summary.failureCode, 'QUALITY');
  assert.deepEqual(summary.qualityCodes, ['reveal-slide-missing']);
  assert.equal(summary.state, 'failed');
  assert.equal(summary.stage, 'outline');
  assert.equal(JSON.stringify(summary).includes('PRIVATE_LESSON'), false);
});

test('checkpoint read failures preserve the original timeout and never retry', async () => {
  for (const response of [null, {ok: false}, {ok: true, json: async () => ({generation_metadata: {outline_status: 'pending'}})}]) {
    let calls = 0;
    const failure = await readOutlineFailure('http://localhost', 'id', {fetchImpl: async () => {
      calls++;
      if (!response) throw new Error('unavailable');
      return response;
    }});
    assert.equal(failure, null);
    assert.equal(calls, 1);
    assert.equal(summarizeProbe({fatalError: {message: 'timeout'}, outlineFailure: failure}).failureCode, 'TIMEOUT');
  }
});

test('private lesson text and arbitrary values cannot enter runner summaries', () => {
  const secret = 'PRIVATE_PAYLOAD_https://secret.example/token';
  const result = summarizeProbe({
    result: { state: secret }, fatalError: { message: 'timeout ' + secret, stack: secret },
    outline: { content: secret }, finalPresentation: {
      generation_metadata: { selected_template: secret }, slides: [{ content: secret }],
    }, imageChecks: [{ url: secret }], streamRequests: [{ body: secret }],
    layoutOverflows: [{ text: secret }],
  });
  assert.equal(result.state, 'failed');
  assert.equal(result.failureCode, 'TIMEOUT');
  assert.equal(result.selectedTemplate, 'unknown');
  assert.equal(result.slideCount, 1);
  assert.equal(JSON.stringify(result).includes(secret), false);
  assert.deepEqual(result.qualityCodes, []);
  assert.ok(Object.entries(result).filter(([key]) => key !== 'qualityCodes')
    .every(([, x]) => typeof x === 'number' || /^[a-zA-Z-]+$/.test(x)));
});

test('failed or incomplete runs cannot become passing summaries', () => {
  assert.equal(summarizeProbe({}).state, 'failed');
  const passed = summarizeProbe({result: {state: 'passed'}, finalPresentation: {
    generation_metadata: {selected_template: 'training-case'}, slides: Array(8).fill({}),
  }});
  assert.equal(passed.state, 'passed');
  assert.equal(passed.slideCount, 8);
  assert.equal(passed.selectedTemplate, 'training-case');
});
