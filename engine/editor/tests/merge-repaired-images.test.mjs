import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { transform } from 'esbuild';

const sourceUrl = new URL('../app/(presentation-generator)/presentation/utils/mergeRepairedImages.ts', import.meta.url);
async function loadMerge() {
  const source = await readFile(sourceUrl, 'utf8');
  const output = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  return import(`data:text/javascript;base64,${Buffer.from(output.code).toString('base64')}`);
}

const deck = (title, url, data = url) => ({ slides: [{ id: 'slide-1',
  content: { heading: { title }, scene: { visual: { image_prompt: '春天花园', image_url: url } } },
  ui: { components: [
    { id: 'scene', elements: [{ type: 'image', name: 'visual', data }] },
    { id: 'heading', elements: [{ type: 'text', name: 'title', runs: [{ text: title }] }] },
  ] },
}] });

test('repair refresh merges only the completed image and preserves local edits', async () => {
  const { mergeRepairedImages } = await loadMerge();
  const local = deck('老师刚修改的标题', '');
  const remote = deck('服务器旧标题', '/app_data/images/repaired.png');
  const result = mergeRepairedImages(local, remote);
  assert.equal(result.slides[0].content.heading.title, '老师刚修改的标题');
  assert.equal(result.slides[0].ui.components[1].elements[0].runs[0].text, '老师刚修改的标题');
  assert.equal(result.slides[0].content.scene.visual.image_url, '/app_data/images/repaired.png');
  assert.equal(result.slides[0].ui.components[0].elements[0].data, '/app_data/images/repaired.png');
  assert.equal(local.slides[0].content.scene.visual.image_url, '');
});

test('manual image and changed prompt win over a late repair result', async () => {
  const { mergeRepairedImages } = await loadMerge();
  const manual = deck('标题', '', '/app_data/images/teacher-choice.png');
  const remote = deck('标题', '/app_data/images/repaired.png');
  assert.equal(mergeRepairedImages(manual, remote).slides[0].content.scene.visual.image_url,
    '/app_data/images/teacher-choice.png');
  const changed = deck('标题', '');
  changed.slides[0].content.scene.visual.image_prompt = '老师的新提示词';
  assert.equal(mergeRepairedImages(changed, remote).slides[0].content.scene.visual.image_url, '');
});
