import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

file = Path(sys.argv[1])
expected = int(sys.argv[2])
issues = []
placeholder = re.compile(r"(?:lorem ipsum|title here|heading|enter text|图片描述|image prompt|negative prompt)", re.I)

try:
    with zipfile.ZipFile(file) as archive:
        names = archive.namelist()
        slides = sorted((name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)), key=lambda name: int(re.search(r"\d+", name).group()))
        if len(slides) != expected:
            issues.append({"code": "SLIDE_COUNT_MISMATCH", "message": f"expected {expected}, received {len(slides)}"})
        for index, name in enumerate(slides, 1):
            root = ET.fromstring(archive.read(name))
            text = " ".join((node.text or "") for node in root.iter() if node.tag.endswith("}t"))
            if not text.strip(): issues.append({"code": "EMPTY_SLIDE", "message": "slide has no visible text", "slideNumber": index})
            if placeholder.search(text): issues.append({"code": "PLACEHOLDER_COPY", "message": "template or production copy is visible", "slideNumber": index})
            for shape in root.iter():
                if shape.tag.endswith("}sp"):
                    has_placeholder = any(child.tag.endswith("}ph") for child in shape.iter())
                    has_text = any((child.text or "").strip() for child in shape.iter() if child.tag.endswith("}t"))
                    if has_placeholder and not has_text: issues.append({"code": "EMPTY_PLACEHOLDER", "message": "empty structural placeholder", "slideNumber": index})
        required = {"[Content_Types].xml", "ppt/presentation.xml"}
        for name in required - set(names): issues.append({"code": "OOXML_PART_MISSING", "message": f"missing {name}"})
except (zipfile.BadZipFile, ET.ParseError, OSError) as error:
    issues.append({"code": "PPTX_INVALID", "message": str(error)})

print(json.dumps({"passed": not issues, "slideCount": len(slides) if 'slides' in locals() else 0, "issues": issues}, ensure_ascii=False))
