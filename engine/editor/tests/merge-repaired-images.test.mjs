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

test('explicit replacement changes only the selected image and preserves local text and geometry', async () => {
  const { mergeRepairedImages } = await loadMerge();
  const local = deck('老师的新标题', '/app_data/images/old.png');
  const remote = deck('旧标题', '/app_data/images/new.png');
  const previous_ui = structuredClone(local.slides[0].ui.components[0].elements[0]);
  local.slides[0].speaker_note = '老师的新讲稿';
  local.slides[0].ui.components[0].elements[0].position = { x: 84, y: 180 };
  const event = { slide_id: 'slide-1', path: ['scene', 'visual'], previous_url: '/app_data/images/old.png', previous_ui, url: '/app_data/images/new.png' };
  const result = mergeRepairedImages(local, remote, [event]);
  assert.equal(result.slides[0].content.scene.visual.image_url, event.url);
  assert.equal(result.slides[0].content.heading.title, '老师的新标题');
  assert.equal(result.slides[0].speaker_note, '老师的新讲稿');
  const image = result.slides[0].ui.components[0].elements[0];
  assert.equal(image.data, event.url);
  assert.equal(image.fit, 'contain');
  assert.equal(image.crop_scale, 1);
  assert.deepEqual(image.position, { x: 84, y: 180 });
  assert.equal(local.slides[0].content.scene.visual.image_url, event.previous_url);
  for (const field of ['data', 'prompt', 'crop_scale']) {
    const edited = structuredClone(local);
    edited.slides[0].ui.components[0].elements[0][field] = field === 'crop_scale' ? 2 : 'manual';
    assert.notEqual(mergeRepairedImages(edited, remote, [event]).slides[0].ui.components[0].elements[0].data, event.url);
  }
  const changed = structuredClone(local);
  changed.slides[0].content.scene.visual.image_prompt = '老师新的主题';
  assert.equal(mergeRepairedImages(changed, remote, [event]).slides[0].content.scene.visual.image_url, event.previous_url);
});
