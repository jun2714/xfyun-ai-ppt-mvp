"""Cover contracts through real schemas, editable UI and the final image request."""
import copy

import pytest

from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui
from models.presentation_outline_model import SlideContentContract, SlideOutlineModel
from models.sql.slide import SlideModel
from services.asset_execution_service import _request_prompt
from services.asset_planning_service import build_asset_plan
from services.classroom_content_mapping import build_classroom_content
from services.research_ppt_generation_context import ResearchPptImageOptions, research_ppt_image_options
from templates.education_variants import EDUCATION_VARIANTS, build_education_variant
from templates.kindergarten_classroom import build_classroom_template
from templates.teacher_training import build_training_template
from templates.v2.schema import get_template_schema


def pack(key):
    if key == 'kindergarten-classroom':
        return build_classroom_template()
    if key == 'teacher-training':
        return build_training_template()
    return build_education_variant(key)


@pytest.mark.parametrize('key', ['kindergarten-classroom', 'teacher-training', *EDUCATION_VARIANTS])
@pytest.mark.parametrize('edited', [False, True])
def test_cover_artwork_has_no_copy_and_renders_below_native_title(key, edited):
    template = pack(key)
    layout = next(item for item in template.layouts['layouts'] if item['id'].endswith('_cover'))
    schema = next(item['schema'] for item in get_template_schema(template.layouts)['layouts']
                  if item['layout_id'] == layout['id'])
    original = '幼儿注意力培养：策略与实施'
    title = '游戏化教学在中班语言领域的应用' if edited else original
    points = ['培训目的：观察证据并讨论支持策略。', '幼儿园园本教研培训']
    outline = SlideOutlineModel(
        content='\n'.join([title, *points]),
        content_contract=SlideContentContract(
            preserve_visible_copy=True, classroom_role='cover-scene', screen_title=original,
            screen_points=points, teacher_note='详细目标和教师讲稿必须完整保留。',
            asset_contracts=[dict(planning_slot='cover-background', semantic_label=original,
                                 description='主题活动位于左侧、右侧留白的无字背景', role='background')],
            required_asset_semantics=[original],
        ),
    )
    content = build_classroom_content(schema, outline)
    assert content['heading']['title'] == title
    assert content['__speaker_note__'] == outline.content_contract.teacher_note
    prompt = content['scene']['visual']['image_prompt']
    assert title in prompt
    if edited:
        assert original not in prompt
    assert all(point not in prompt for point in points)
    assert outline.content_contract.teacher_note not in prompt
    assert '汉字、英文、字母、数字' in prompt
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    ids = [component['id'] for component in ui['components']]
    assert ids.index('scene') < ids.index('cover_panel') < ids.index('heading')
    panel = next(c for c in ui['components'] if c['id'] == 'cover_panel')['elements'][0]
    assert panel['fill'] == {'color': '#FFFFFF', 'opacity': 1.0}
    for component in ui['components']:
        for element in component['elements']:
            if element['type'] == 'text':
                x, y = element['position']['x'], element['position']['y']
                assert x >= 544 and x + element['size']['width'] <= 1232
                assert y >= 48 and y + element['size']['height'] <= 672
    slide = SlideModel(presentation='00000000-0000-0000-0000-000000000001',
                       layout_group=key, layout=layout['id'], index=0, content=content, ui=ui)
    plan = build_asset_plan([slide])
    assert len(plan) == 1
    assert plan[0].generation_mode == 'direct-background'
    slot = plan[0].slots[0]
    assert (slot.width, slot.height, slot.aspect_ratio, slot.text_safe_area) == (1280, 720, '16:9', 'right')
    assert slot.required
    # English lesson options must never allow painted titles on the cover.
    token = research_ppt_image_options.set(ResearchPptImageOptions(enabled=True, forbid_latin_text=False))
    try:
        final_prompt = _request_prompt(plan[0])
        assert '禁止任何语言的文字' in final_prompt
        assert '图内文字可以使用英文' not in final_prompt
        assert 'warm cream' not in final_prompt
        assert '浅米白、松石绿、雾蓝；' not in final_prompt
    finally:
        research_ppt_image_options.reset(token)
    # Reopening a completed cover must not schedule another paid background.
    content['scene']['visual']['image_url'] = '/app_data/images/completed-cover.png'
    assert build_asset_plan([slide.model_copy(update={'content': content})]) == []
