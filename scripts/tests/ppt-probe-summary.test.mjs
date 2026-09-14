import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeProbe } from '../lib/ppt-probe-summary.mjs';

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
  assert.ok(Object.values(result).every(x => typeof x === 'number' || /^[a-zA-Z-]+$/.test(x)));
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
