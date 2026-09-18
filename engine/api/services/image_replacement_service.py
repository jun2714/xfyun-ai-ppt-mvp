"""Snapshot a single explicit replacement; attach only if the teacher's image is unchanged."""
import hashlib

from fastapi import HTTPException
from models.json_path_guide import JsonPathGuide
from services.asset_planning_service import extract_asset_slots, REPAIR_FAILED_PROMPT_KEY, REPAIR_FAILED_REASON_KEY
from utils.dict_utils import get_dict_at_path
from utils.process_slides import IMAGE_PROMPT_KEYS, _asset_dicts_with_prompt


def _images(slide, slot):
    keys = [getattr(g, 'key', None) for g in slot.content_path.guides]
    found = []
    def visit(value):
        if isinstance(value, dict):
            if value.get('type') == 'image' and value.get('name') == slot.slot_name:
                found.append(value)
            else:
                for item in value.values():
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for component in (slide.ui or {}).get('components', []):
        if keys and component.get('id') == keys[0]:
            visit(component)
    return found


def replaceable_images(slides):
    from services.image_repair_service import image_url, resolved
    items = []
    for slide in slides:
        candidate = slide.model_copy(deep=True)
        for _, parent, _ in _asset_dicts_with_prompt(candidate.content, IMAGE_PROMPT_KEYS):
            parent.pop('image_url', None)
            parent.pop('__image_url__', None)
        for slot in extract_asset_slots([candidate], include_blocked=True):
            parent = get_dict_at_path(slide.content, slot.content_path)
            images = _images(slide, slot)
            if len(images) != 1:
                continue
            url = images[0].get('data')
            if not resolved(url):
                continue
            key = hashlib.sha256(f'{slide.id}:{slot.consumer_id}'.encode()).hexdigest()[:24]
            items.append(dict(key=key, slide_id=str(slide.id), page=slide.index + 1,
                              slot=slot.slot_name, url=url, content_url=image_url(parent),
                              prompt=slot.prompt, path=slot.content_path.model_dump(), ui=images[0]))
    return items


def replacement_snapshot(slides, key, expected_url):
    item = next((item for item in replaceable_images(slides) if item['key'] == key), None)
    if item is None or item['url'] != expected_url:
        raise HTTPException(409, '图片已发生变化，请重新选择要替换的图片。')
    return item


def prepare_replacement(slides, snapshot):
    """Clear only a detached worker copy; the saved original remains visible."""
    from services.image_repair_service import image_url
    source = next((s for s in slides if str(s.id) == snapshot['slide_id']), None)
    if source is None:
        raise HTTPException(409, '原页面已删除，本次换图已停止。')
    slide = source.model_copy(deep=True)
    path = JsonPathGuide.model_validate(snapshot['path'])
    parent = get_dict_at_path(slide.content, path)
    if image_url(parent) != snapshot['content_url'] or (parent.get('image_prompt') or parent.get('__image_prompt__')) != snapshot['prompt']:
        raise HTTPException(409, '图片或提示词已修改，本次换图已停止。')
    # Block other missing images in this detached slide without altering their saved marks.
    for _, value, prompt in _asset_dicts_with_prompt(slide.content, IMAGE_PROMPT_KEYS):
        value[REPAIR_FAILED_PROMPT_KEY] = prompt
    parent.pop('image_url', None)
    parent.pop('__image_url__', None)
    parent.pop(REPAIR_FAILED_PROMPT_KEY, None)
    parent.pop(REPAIR_FAILED_REASON_KEY, None)
    slot = next(s for s in extract_asset_slots([slide]) if s.content_path == path)
    if _images(source, slot) != [snapshot['ui']]:
        raise HTTPException(409, '画布中的图片已修改，本次换图已停止。')
    for image in _images(slide, slot):
        image.update(data='', fit='contain', crop_scale=1, focus_x=50, focus_y=50)
    return [slide], slot


def merge_replacement(generated, latest, snapshot, slot):
    from services.image_repair_service import image_url, resolved
    from services.asset_execution_service import _assign_url
    if str(latest.id) != snapshot['slide_id']:
        return None
    try:
        source = get_dict_at_path(generated.content, slot.content_path)
        target = get_dict_at_path(latest.content, slot.content_path)
    except (KeyError, IndexError, TypeError):
        return None
    url = image_url(source)
    if (not resolved(url) or image_url(target) != snapshot['content_url']
            or (target.get('image_prompt') or target.get('__image_prompt__')) != snapshot['prompt']
            or _images(latest, slot) != [snapshot['ui']]):
        return None
    _assign_url(latest, slot, url)
    target['__image_replacement__'] = dict(previous_url=snapshot['content_url'],
                                          previous_ui=snapshot['ui'], url=url)
    for image in _images(latest, slot):
        image.update(data=url, fit='contain', crop_scale=1, focus_x=50, focus_y=50)
    path = [g.key if hasattr(g, 'key') else g.index for g in slot.content_path.guides]
    return dict(slide_id=str(latest.id), path=path, previous_url=snapshot['content_url'],
                previous_ui=snapshot['ui'], url=url)


def preserve_replacement_result(source, target):
    """An autosave started before replacement must not restore the old image.

    Once the client has seen the replacement marker it may edit/undo normally.
    Only old image values are merged; the incoming text and geometry stay intact.
    """
    from services.image_repair_service import image_url, resolved
    from services.asset_execution_service import _assign_url
    changed = 0
    candidate = source.model_copy(deep=True)
    for _, parent, _ in _asset_dicts_with_prompt(candidate.content, IMAGE_PROMPT_KEYS):
        parent.pop('image_url', None)
        parent.pop('__image_url__', None)
    for slot in extract_asset_slots([candidate], include_blocked=True):
        old = get_dict_at_path(source.content, slot.content_path)
        marker = old.get('__image_replacement__')
        if not marker or not resolved(marker.get('url')) or image_url(old) != marker['url']:
            continue
        try:
            dest = get_dict_at_path(target.content, slot.content_path)
        except (KeyError, IndexError, TypeError):
            continue
        if dest.get('__image_replacement__') == marker:
            continue
        if image_url(dest) != marker['previous_url'] or (dest.get('image_prompt') or dest.get('__image_prompt__')) != slot.prompt:
            continue
        images = _images(target, slot)
        keys = ('data', 'prompt', 'fit', 'crop_scale', 'focus_x', 'focus_y')
        if len(images) != 1 or any(images[0].get(k) != marker['previous_ui'].get(k) for k in keys):
            continue
        _assign_url(target, slot, marker['url'])
        dest['__image_replacement__'] = marker
        images[0].update(data=marker['url'], fit='contain', crop_scale=1, focus_x=50, focus_y=50)
        changed += 1
    return changed
