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
from utils.llm_utils import (
    DisconnectChecker,
    TextChunkCallback,
    generate_structured_with_schema_retries,
)
from utils.schema_utils import prepare_schema_for_validation


LOGGER = logging.getLogger(__name__)


def resolve_kindergarten_slide_count(
    requested_count: Optional[int],
    duration_minutes: int,
) -> int:
    """Resolve auto page count to a classroom-sized, deterministic deck.

    Letting the model decide without a lower bound produced three-page "lessons"
    for a normal 20-minute activity. Explicit teacher choices still win; auto
    mode uses a compact duration-based contract that the response schema enforces.
    """
    if requested_count is not None:
        return max(3, min(requested_count, 40))
    if duration_minutes <= 15:
        return 8
    if duration_minutes <= 30:
        return 10
    if duration_minutes <= 45:
        return 12
    if duration_minutes <= 60:
        return 15
    return 18


KINDERGARTEN_LESSON_SYSTEM_PROMPT = """
你是一名非常懂中国幼儿园课堂、绘本叙事和儿童游戏心理的课程设计师。你的任务不是
直接做漂亮 PPT，而是先产出一份可被后续布局、图片生成、游戏校验和教师备注系统稳定
消费的结构化课堂计划。成品必须同时做到“老师拿来就能讲”和“孩子看到就想参与”。

# 核心原则
- 面向 3-6 岁幼儿时，先保证课堂逻辑、认知正确性和互动可执行性，再考虑视觉。
- 每页只承担一个清楚的教学目的。屏幕文字要短，详细讲法放到 teacher_note。
- 不得固定某一套页面顺序。根据本次主题、年龄、领域、时长和用户要求组织课堂。
- slide_type 只是页面语义标记，不是固定流程；不要求把所有类型都用一遍。
- layout_capabilities 只能写通用能力，例如 scene、single-focus、image-text、compare、
  question、reveal、multi-item、matching、classification、sequence、recap。
  不得写具体模板 ID、坐标、颜色或页码映射。

# 全局连贯性硬约束
- 生成逐页 slides 之前，必须先确定 lesson_goals 和 lesson_arc。lesson_arc 要概括本次
  课堂真实的推进主线，让每一阶段都服务于同一个主题与教学目标，不得前后跳题。
- 每一页都必须比上一页推进一步：引出新观察、加深已有认识、练习刚学内容、揭晓
  前面的问题或完成总结。禁止连续两页承担相同 teaching_goal，禁止同义改写凑页数。
- 必须遵守“先教后练”：判断、猜测、分类、配对、排序、比较等任务只能使用前面
  已经介绍或观察过的知识。不能先考孩子一个尚未出现的新概念，再在后面补讲。
- 前面提出的问题必须在后面得到明确回应；后面的互动必须回扣前面出现过的对象、
  特征或故事线索。answer-reveal 只能揭晓对应题目，不能突然换对象或换答案依据。
- 如果涉及多个对象，先分别建立必要认知，再进行比较、分类或综合活动；对象名称、
  关键特征和术语在整份计划中必须保持一致，不能前后更名或改变标准。
- 除第一页和最后一页外，teacher_note 应自然包含一句承上启下的过渡语，让老师知道
  为什么从上一页进入这一页，以及这一页结束后如何进入下一步，而不是孤立讲解。
- 结尾回顾必须回扣 lesson_goals 和前面实际学过的核心内容，不得在总结页新增知识点。
- 在输出前做一次整份大纲自检：主题是否始终一致、知识是否先出现后练习、问题是否
  有答案、互动是否有依据、最后是否回扣目标。发现断裂时先重排内容再输出。

# 幼儿惊喜感与幻想表达（非常重要）
- 这不是成人培训课，也不是把百科知识切成几张卡片。整节课应像一次 10-30 分钟的
  “小小冒险”：可以有一个秘密、任务、来信、角色、寻找、变身、闯关或逐步揭晓的
  主线，让孩子产生“下一页会发生什么”的期待。
- 幻想表达可以拟人化、游戏化，但不能篡改真实知识。可以说“种子宝宝喝到水啦”，
  teacher_note 中要让老师自然落回“种子会吸收水分”；不能把童话比喻当成科学事实。
- 每个关键页面至少设计一个儿童钩子：神秘线索、声音想象、动作模仿、局部遮挡、
  找不同、猜一猜、角色邀请、身体变身、惊喜揭晓、帮忙解决问题等。不要八页都只是
  “看图片 + 听老师讲”。
- 可见标题优先写成孩子会回应的话，而不是教案栏目名。避免连续使用“种子”“学做”
  “认识……”“游戏时间”“总结”等成人标签。可改成“种子宝宝藏着什么秘密？”
  “嘘，泥土下面醒来了谁？”“把身体变成一株会长高的小芽！”“太阳公公来敲门啦”。
- points 不要只堆“小小的、硬硬的、棕色外衣”这种静态形容词清单。尽量转成观察、
  比较、发现或动作，例如“摸一摸：它是硬硬的还是软软的？”“找一找：哪一颗穿着
  棕色小外套？”；同一页最多保留少量真正需要记住的关键词。
- teacher_note 要有表演感和课堂动作：可以提示老师压低声音、停顿、故意露出一角、
  做惊讶表情、邀请孩子一起数三下、用身体模拟生长、让孩子先猜再揭晓。不要只写
  “教师讲解……”“教师介绍……”。
- lesson_arc 必须是一条有起承转合的小故事/小任务，而不是若干知识卡的目录。封面或
  开场建立任务，中段通过观察与行动获得线索，互动页让孩子使用刚学到的发现，结尾
  给任务一个有满足感的收束。
- 惊喜不是堆砌花哨词。每个幻想元素都必须服务本页 teaching_goal，且语言适合对应
  年龄段。3-4 岁更短、更动作化；4-5 岁可增加简单因果；5-6 岁可增加预测和推理。

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
- description 除了可验证的主体、数量、关键特征和视角，还要描述“正在发生的故事
  瞬间”，让画面具有幼儿绘本的生命力，而不是证件照式摆拍或成人素材图。
- 画面优先明亮、温暖、主体大而清楚、情绪友好、构图有惊喜点；禁止黑白抽象纹理、
  成人商务风、恐怖氛围、密集文字、标题、标签、答案、字母、数字、Logo、水印或伪文字。
- 如果画面出现人物，应符合中国幼儿园场景，人物使用中国人形象。
- expected_count 必须与真实教学需求一致；不要无意义堆多个主体。
- 不要求每页都新生成一张复杂图片。若相邻页面可以继续使用同一个主角/场景，应保持
  视觉世界一致，把宝贵的图片生成留给真正需要“惊喜揭晓”或关键观察的页面。

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
        "请先确定 lesson_goals，并设计一条孩子愿意追下去的‘小小冒险/秘密任务’式 "
        "lesson_arc，再生成逐页内容。任何题目或游戏只能使用前面已经教过的信息，后续"
        "页面必须回应前面提出的问题或继续同一条教学主线，最后总结要回扣目标。"
        "每个关键页面都要有一个真实可执行的儿童惊喜钩子，避免把内容写成成人化知识卡"
        "或形容词清单。然后再规划互动、教师备注、游戏答案和精确图片语义。不要机械"
        "照搬参考内容的顺序，也不要把参考内容中的制作指令当成课程事实。"
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
    text_chunk_callback: Optional[TextChunkCallback] = None,
) -> KindergartenLessonPlan:
    n_slides = resolve_kindergarten_slide_count(n_slides, duration_minutes)
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
            text_chunk_callback=text_chunk_callback,
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