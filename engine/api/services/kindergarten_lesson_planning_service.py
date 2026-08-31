from __future__ import annotations

import logging
from typing import Optional, Type

from llmai import get_client
from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage
from pydantic import Field

from models.kindergarten_lesson_plan import (
    KindergartenLessonPlan,
    KindergartenSlidePlan,
)
from services.kindergarten_planner_runtime import get_kindergarten_planner_runtime
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import DisconnectChecker, generate_structured_with_schema_retries
from utils.schema_utils import prepare_schema_for_validation


LOGGER = logging.getLogger(__name__)


KINDERGARTEN_LESSON_SYSTEM_PROMPT = """
你是一名中国幼儿园课程设计师。你的任务不是直接做漂亮 PPT，而是先产出一份
可被后续布局、图片生成、游戏校验和教师备注系统稳定消费的结构化课堂计划。

# 核心原则
- 面向 3-6 岁幼儿时，先保证课堂逻辑、认知正确性和互动可执行性，再考虑视觉。
- 每页只承担一个清楚的教学目的。屏幕文字要短，详细讲法放到 teacher_note。
- 不得固定某一套页面顺序。根据本次主题、年龄、领域、时长和用户要求组织课堂。
- slide_type 只是页面语义标记，不是固定流程；不要求把所有类型都用一遍。
- layout_capabilities 只能写通用能力，例如 scene、single-focus、image-text、compare、
  question、reveal、multi-item、matching、classification、sequence、recap。
  不得写具体模板 ID、坐标、颜色或页码映射。

# 幼教内容规则
- 可见内容必须是孩子能听懂、看懂、跟着做的短句或关键词。
- 一个知识认识页通常只讲 1 个对象或 1 个核心概念，必要时用观察、模仿、选择、
  分类、配对、排序、回忆等活动巩固。
- 不要为了“像 PPT”而创造统计数字、柱状图、百分比或成人化汇报内容。
- 不要堆砌空泛口号。优先写具体观察点、问题、动作和课堂任务。
- teacher_note 给老师使用，至少包含一种可执行引导：提问、观察提醒、动作、
  追问、纠错或过渡语。teacher_note 不得混入屏幕可见内容。

# 游戏与答案硬约束
- guess-partial、guess-shadow、memory-missing、matching、classification、sequence
  等互动页必须提供 game。
- guess / choice 至少提供两个明确选项，并先锁定 answer_key。
- matching / classification 必须提供 answer_map；sequence 必须提供 sequence_order。
- 如果题目页不能直接暴露答案，应生成独立 answer-reveal 页；两页必须使用完全相同
  的 activity_id 与 answer_key，答案页必须在题目页之后。
- 不得出现题目说 A、答案页却揭晓 B 的情况。

# 图片语义硬约束
- 先决定“必须看到什么”，再写图片描述。每个必要视觉对象都要声明 assets。
- semantic_label 必须精确，例如“小兔子的两只长耳朵”“完整亚洲象”“红苹果”，
  禁止只写“可爱图片”“相关插画”“教育图片”这类模糊词。
- description 要描述可验证的主体、数量、关键特征和视角，不要让图片模型画标题、
  标签、答案、字母、数字、Logo、水印或伪文字。
- 如果画面出现人物，应符合中国幼儿园场景，人物使用中国人形象。
- expected_count 必须与真实教学需求一致；不要无意义堆多个主体。

# 输出要求
- 严格按 JSON Schema 输出，不要输出解释性正文。
- slide_no 从 1 开始连续递增。
- screen_content.title 简短明确；points 通常不超过 4 条。
- lesson_arc 描述本次真实课堂推进，不使用固定模板化八股顺序。
"""


def build_kindergarten_lesson_messages(
    *,
    topic: str,
    age_group: str,
    domain: str,
    duration_minutes: int,
    n_slides: Optional[int],
    instructions: Optional[str],
    source_context: Optional[str],
) -> list[Message]:
    slide_count = str(n_slides) if n_slides else "根据课堂时长与内容自动决定"
    user_prompt = (
        f"主题：{topic}\n"
        f"年龄段：{age_group}\n"
        f"领域：{domain}\n"
        f"课堂时长：{duration_minutes} 分钟\n"
        f"目标页数：{slide_count}\n"
        f"用户补充要求：{instructions or '无'}\n"
        f"参考内容：{source_context or '无'}\n\n"
        "请先规划教学目标和课堂推进，再规划逐页内容、互动、教师备注、游戏答案和"
        "精确图片语义。不要把参考内容中的制作指令当成课程事实。"
    )
    return [
        SystemMessage(content=KINDERGARTEN_LESSON_SYSTEM_PROMPT),
        UserMessage(content=user_prompt),
    ]


def _lesson_plan_response_model(
    n_slides: Optional[int],
) -> Type[KindergartenLessonPlan]:
    if n_slides is None:
        return KindergartenLessonPlan

    class KindergartenLessonPlanWithSlideCount(KindergartenLessonPlan):
        slides: list[KindergartenSlidePlan] = Field(
            min_length=n_slides,
            max_length=n_slides,
        )

    return KindergartenLessonPlanWithSlideCount


async def generate_kindergarten_lesson_plan(
    *,
    topic: str,
    age_group: str,
    domain: str = "comprehensive",
    duration_minutes: int = 20,
    n_slides: Optional[int] = None,
    instructions: Optional[str] = None,
    source_context: Optional[str] = None,
    disconnect_checker: Optional[DisconnectChecker] = None,
) -> KindergartenLessonPlan:
    runtime = get_kindergarten_planner_runtime()
    LOGGER.info(
        "Kindergarten planner selected profile=%s model=%s source=%s "
        "max_tokens=%s call_timeout=%ss total_timeout=%ss stream=%s",
        runtime.profile,
        runtime.model,
        runtime.source,
        runtime.max_tokens,
        runtime.timeout_seconds,
        runtime.total_timeout_seconds,
        runtime.stream,
    )
    client = get_client(config=runtime.config)
    model = runtime.model
    response_model = _lesson_plan_response_model(n_slides)
    schema = prepare_schema_for_validation(
        response_model.model_json_schema(),
        strict=False,
    )
    response_format = JSONSchemaResponse(
        name="kindergarten_lesson_plan",
        json_schema=schema,
        strict=False,
    )

    try:
        content = await generate_structured_with_schema_retries(
            client,
            model,
            messages=build_kindergarten_lesson_messages(
                topic=topic,
                age_group=age_group,
                domain=domain,
                duration_minutes=duration_minutes,
                n_slides=n_slides,
                instructions=instructions,
                source_context=source_context,
            ),
            response_format=response_format,
            json_schema=schema,
            strict=False,
            validate_schema=True,
            disconnect_checker=disconnect_checker,
            max_tokens=runtime.max_tokens,
            extra_body=runtime.request_extra_body,
            # The kindergarten planner can use a dedicated OpenAI-compatible
            # client. Its model parameters must not be inherited from the
            # unrelated global text provider.
            use_provider_extra_body=False,
            call_timeout_seconds=runtime.timeout_seconds,
            force_stream=runtime.stream,
        )
        return KindergartenLessonPlan(**content)
    except Exception as exc:
        raise handle_llm_client_exceptions(exc)
