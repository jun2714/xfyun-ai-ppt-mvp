from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass


_ENGLISH_TEACHING_RE = re.compile(
    r"英语|英文|english|phonics|自然拼读|字母教学|英文课",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResearchPptImageOptions:
    enabled: bool = False
    forbid_latin_text: bool = True


research_ppt_image_options: ContextVar[ResearchPptImageOptions] = ContextVar(
    "research_ppt_image_options",
    default=ResearchPptImageOptions(),
)


def looks_like_english_teaching_request(*texts: object) -> bool:
    blob = " ".join(str(part or "") for part in texts)
    return bool(_ENGLISH_TEACHING_RE.search(blob))
