"""CJK fonts for library/HTML slide previews on Linux.

Kindergarten PPTX files typically name 微软雅黑 / 黑体. Chromium on the Baota
server does not have those families, so glyphs render as tofu squares.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from utils.get_env import get_app_data_directory_env

LOGGER = logging.getLogger(__name__)

CJK_PREVIEW_MARK = "cjk-v1"
CJK_FAMILY = "TeachNova CJK"
CJK_FONT_ALIASES = (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "微软雅黑",
    "SimHei",
    "黑体",
    "SimSun",
    "宋体",
    "NSimSun",
    "KaiTi",
    "楷体",
    "FangSong",
    "仿宋",
    "DengXian",
    "等线",
    "YouYuan",
    "幼圆",
    "STHeiti",
    "STSong",
    "PingFang SC",
    "Hiragino Sans GB",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
)

_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _iter_font_candidates() -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        real = os.path.realpath(path)
        if real in seen or not os.path.isfile(real):
            return
        seen.add(real)
        found.append(real)

    for path in _CJK_FONT_CANDIDATES:
        add(path)

    app_data = get_app_data_directory_env()
    search_roots = [
        os.path.expanduser("~/.local/share/fonts"),
        "/usr/local/share/fonts",
        "/usr/share/fonts",
    ]
    if app_data:
        search_roots.insert(0, os.path.join(app_data, "fonts"))

    patterns = (
        "*NotoSansCJK*SC*.otf",
        "*NotoSansCJKsc*.otf",
        "*NotoSansSC*.otf",
        "*SourceHanSans*SC*.otf",
        "*wqy-microhei*",
        "*DroidSansFallback*.ttf",
        "*NotoSansCJK*.ttc",
    )
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for pattern in patterns:
            for path in glob.glob(os.path.join(root, "**", pattern), recursive=True):
                add(path)
    return found


def discover_cjk_font_file() -> str | None:
    files = _iter_font_candidates()
    if not files:
        return None
    preferred = [
        path for path in files if path.lower().endswith((".otf", ".ttf", ".woff2", ".woff"))
    ]
    return (preferred or files)[0]


@lru_cache(maxsize=1)
def ensure_cjk_preview_font() -> str | None:
    source = discover_cjk_font_file()
    if not source:
        LOGGER.warning(
            "[ppt.cjk] 服务器没有中文字体。请安装 fonts-noto-cjk 或 wqy-microhei 后重启 API。"
        )
        return None

    app_data = get_app_data_directory_env()
    if not app_data:
        return source

    dest_dir = os.path.join(app_data, "fonts")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"cjk-preview-fallback{Path(source).suffix.lower() or '.ttf'}")
    try:
        if not os.path.isfile(dest) or os.path.getsize(dest) != os.path.getsize(source):
            shutil.copy2(source, dest)
        user_fonts = os.path.expanduser("~/.local/share/fonts")
        os.makedirs(user_fonts, exist_ok=True)
        user_copy = os.path.join(user_fonts, os.path.basename(dest))
        if not os.path.isfile(user_copy):
            shutil.copy2(dest, user_copy)
            subprocess.run(
                ["fc-cache", "-f", user_fonts],
                check=False,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        LOGGER.exception("[ppt.cjk] failed to stage CJK preview font")
        return source
    return dest if os.path.isfile(dest) else source


def has_preview_cjk_font() -> bool:
    return bool(ensure_cjk_preview_font())


def cjk_preview_font_css() -> str:
    font_path = ensure_cjk_preview_font()
    if not font_path:
        return ""
    font_url = Path(font_path).resolve().as_uri()
    families = (CJK_FAMILY,) + CJK_FONT_ALIASES
    rules = [
        (
            "@font-face { "
            f'font-family: "{family}"; '
            f'src: url("{font_url}"); '
            "font-weight: 100 900; "
            "font-style: normal; "
            "font-display: block; "
            "}"
        )
        for family in families
    ]
    stack = ", ".join(f'"{name}"' for name in (CJK_FAMILY,) + CJK_FONT_ALIASES)
    rules.append(
        "html, body, #slide-preview-root { "
        f"font-family: {stack}, sans-serif; "
        "}"
    )
    return "\n".join(rules)


def append_cjk_font_stack(css_or_html: str) -> str:
    if not css_or_html:
        return css_or_html

    def replace(match: object) -> str:
        prefix, value, suffix = match.group(1), match.group(2), match.group(3)
        stripped = value.strip()
        if not stripped or stripped.lower() == "inherit" or CJK_FAMILY in stripped:
            return match.group(0)
        return f'{prefix}{stripped}, "{CJK_FAMILY}", sans-serif{suffix}'

    return re.sub(
        r"(font-family\s*:\s*)([^;}{]+)([;}])",
        replace,
        css_or_html,
        flags=re.IGNORECASE,
    )
