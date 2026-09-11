from __future__ import annotations

import logging
from typing import Literal, Optional, Type

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
KindergartenContentMode = Literal["classroom", "training"]


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
- 每个 lesson_goal 都必须在正文中有对应的观察或操作，不能只出现在封面目标里。
  若页数不足以讲清所有目标，应在规划时收窄目标，不要遗漏目标后仍声称已经完成。
- 全篇最多安排一页纯回顾。排序练习之后不要再连续两页换措辞复述同一组步骤；
  结尾用一个可当场完成或课后继续的具体观察任务收束，让孩子带着新问题离开。
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
  连贯体验：可以有秘密、任务、来信、寻找、动作或逐步揭晓，让孩子产生期待；但这些
  只是表达手段，绝不能另造一个与用户主题无关的动物、IP 或童话角色来替代真实主角。
- 用户原始主题是不可替换的语义锚点。生成前先在内部识别：真实主角/对象是谁、要认识
  或经历的核心变化是什么、最终教学目标是什么。lesson_goals、lesson_arc、每页
  teaching_goal 与可见内容都必须服务这三个锚点，不能只借用主题标题后另讲一个故事。
- 用户没有明确提出的动物、拟人角色、IP、魔法角色或虚构朋友，只能偶尔作为单页表达
  手段，不能进入 lesson_arc，不能连续出现，不能替代真实主角或成为需要学习的对象。
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
- 屏幕不是教案：title 尽量 8-20 字，points 通常 0-3 条、每条尽量不超过 18 字。
  长解释、教师动作、预期回答与过渡语放 teacher_note 或 interaction.instruction。
  screen_content.instruction 只放孩子直接执行的一句短指令，不重复 points。
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
- 每页至少提供一张有明确教学用途的 required 图片，包括开场、回顾和结束页。
- 比较、排序、回顾中若一个 point 对应一张图，必须在该 asset 的 audience_text
  逐字复制这个 point；图文靠该字段配对，绝不靠 assets 数组顺序猜测。
  一张图只绑定一个 point，每个 point 只绑定一张图。完整场景图不填 audience_text。
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
- 第 1 页必须为 cover-scene 封面，呈现用户主题、活动目标与使用类型。目标总页数已经
  包含封面、提问和对应揭晓页；在总页数内安排完整教学过程，不得把封面当作额外一页。
- 涉及自然科学时先核对概念边界：种子萌发通常需要水、空气和适宜温度；不要把阳光
  写成所有种子萌发的必需条件。区分先长出的根和后来露出地面的芽。
- 题目与揭晓必须分开页面。没有相应答案页时不要设计需要揭晓的猜测游戏；
  绝不在提问 points 中同时写“答案是…”“先出现的是…”等结论。
- 严格按 JSON Schema 输出，不要输出解释性正文。
- slide_no 从 1 开始连续递增。
- screen_content.title 简短明确；points 通常不超过 4 条。
- lesson_arc 描述本次真实课堂推进，不使用固定模板化八股顺序。
"""

KINDERGARTEN_TRAINING_SYSTEM_PROMPT = """
你是一名熟悉中国幼儿园园本教研、教师培训和课程改革的专业教研策划师。请产出一份
面向幼儿园教师、教研组或园长的结构化培训计划，而不是面向幼儿直接授课的课堂脚本。

# 内容质量硬约束
- 先从用户给出的现存问题出发，不得擅自换成儿童知识主题。
- lesson_goals 聚焦教师理解、诊断与改进能力；lesson_arc 应形成“问题呈现—原因分析—
  理念澄清—案例对比—改进策略—实施步骤—评价与复盘”的闭环，但可按主题灵活调整。
- 第 1 页必须是 slide_type=cover-scene 的真正标题页：标题直接使用培训核心主题，points
  只写一条“培训目的”和一条“幼儿园园本教研培训”，不得显示时长、操作指令、课堂提问，
  也不得直接进入案例正文。
- 至少安排 1 页 compare：左侧写“主观判断/模糊感受”，右侧写“客观事实/可观察证据”，
  screen_content.points 必须正好 2 条并分别以“主观判断：”“客观证据：”开头，明确告诉
  教师哪些是判断、哪些是证据，不能只罗列两段普通正文。
- 用户输入中出现“问题、现存、为何、怎么、如何、疑问”等表达时，至少用 2 页回应：
  一页呈现“具体问题与影响”，一页呈现“原因—解决动作—验证指标”；不得回避原问题。
  问题解决页优先使用 sequence 且正好 3 条 points，依次为“问题表现：”“解决动作：”
  “验证指标：”，使页面能直接回答教师最关心的怎么做。
- 每页必须推进一个新的论点、证据、案例或行动，不得用同义标题和空泛口号凑页数。
- 可见标题和 points 使用专业、清晰、可汇报的教师语言。禁止“宝宝、猜一猜、闯关、
  小小冒险、太阳公公”等儿童口吻，禁止设计面向幼儿的游戏。
- 字数按页面任务变化：封面不超过 70 字；观点页约 70—130 字；主客观对照、案例分析、
  问题解决和实施路径页可到 160 字。需要丰富表达时增加有效事实、例子和行动，不写空话。
  超过版式容量时只保留关键词和核心结论，把详细解释放进 teacher_note。
- teacher_note 补充讲解逻辑、案例展开、研讨问题或落地提醒，不重复屏幕文字。
- 用户提供的关键事实、问题和目标必须在大纲中有明确对应，不能只借用少量关键词。

# 图片与版式
- 图片服务于真实园所环境、教师研讨、课程推进、区域材料调整、儿童学习痕迹或前后案例
  对比；不要使用童趣绘本、拟人角色、成人商务海报和无关装饰图。
- semantic_label 必须短而具体，例如“主题墙调整前后对比”“教师观察儿童游戏记录”。
- layout_capabilities 只写 scene、single-focus、image-text、compare、multi-item、sequence、
  recap 等通用能力，不写模板 ID、坐标或颜色。

# 输出要求
- 严格按 JSON Schema 输出，不要输出解释性正文。
- slide_no 从 1 开始连续递增。
- 输出前自检：是否忠于用户主题、问题与策略是否闭环、页面是否有层次且可直接培训使用。
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
    content_mode: KindergartenContentMode = "classroom",
) -> list[Message]:
    slide_count = str(n_slides) if n_slides else "根据课堂时长与内容自动决定"
    if content_mode == "training":
        topic_focus = topic
        for separator in ("，", "。", "；", ";", "\n"):
            topic_focus = topic_focus.split(separator, 1)[0]
        topic_focus = topic_focus.strip()[:60] or topic[:60]
        user_prompt = (
            f"教研培训主题：{topic}\n"
            f"必须贯穿全篇的核心主题：{topic_focus}\n"
            f"目标对象：{age_group}\n"
            f"内容领域：{domain}\n"
            f"预计培训时长：{duration_minutes} 分钟\n"
            f"目标页数：{slide_count}\n"
            f"用户补充要求：{instructions or '无'}\n"
            f"参考内容：{source_context or '无'}\n\n"
            "请完整保留用户提出的现存问题和改进目标，先提炼核心矛盾，再生成可直接用于"
            "教师培训的逐页大纲。大纲必须包含问题证据、原因诊断、理念转变、案例对照、"
            "具体策略、实施步骤和复盘指标，并保证每页承担不同作用。不得写成幼儿课堂，"
            "不得出现儿童口吻、猜谜、闯关或知识卡片式内容。封面标题必须直接使用上述"
            "核心主题；后续每一页都必须回答这个主题中的问题，禁止替换成观察记录、教师"
            "成长或其他相邻但不同的培训主题。必须明确区分主观判断与客观证据，并针对"
            "用户提出的疑问展示“遇到什么问题—为什么发生—如何解决—怎样验证”。"
        )
        return [
            SystemMessage(content=KINDERGARTEN_TRAINING_SYSTEM_PROMPT),
            UserMessage(content=user_prompt),
        ]
    user_prompt = (
        f"主题：{topic}\n"
        f"年龄段：{age_group}\n"
        f"领域：{domain}\n"
        f"课堂时长：{duration_minutes} 分钟\n"
        f"目标页数：{slide_count}\n"
        f"用户补充要求：{instructions or '无'}\n"
        f"参考内容：{source_context or '无'}\n\n"
        "把上述原始主题作为最高优先级语义锚点。先在内部确定主题的真实主角/对象、"
        "核心变化或认知任务、最终教学目标，再确定 lesson_goals，并设计一条忠于"
        "这些锚点、孩子愿意参与的连贯 "
        "lesson_arc，再生成逐页内容。任何题目或游戏只能使用前面已经教过的信息，后续"
        "页面必须回应前面提出的问题或继续同一条教学主线，最后总结要回扣目标。"
        "每个关键页面都要有一个真实可执行的儿童惊喜钩子，避免把内容写成成人化知识卡"
        "或形容词清单。用户未提出的新角色不得进入 lesson_arc 或连续出现在多页中。"
        "然后再规划互动、教师备注、游戏答案和精确图片语义。不要机械"
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
    content_mode: KindergartenContentMode = "classroom",
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
                content_mode=content_mode,
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
