"""Build SVG examples from the actual template geometry.

Run: engine/api/.venv/bin/python scripts/build-education-previews.py --font /path/to/CJK-font.otf
Illustrations are original native vector placeholders, not generated lesson assets.
"""
import argparse
import sys
from pathlib import Path
from html import escape
API_ROOT = Path(__file__).resolve().parents[1] / "engine" / "api"
sys.path.insert(0, str(API_ROOT))
from templates.education_variants import EDUCATION_VARIANTS, build_education_variant
from templates.teaching_activity import ACTIVITY_STYLES, build_activity_template
from PIL import ImageFont
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--font', required=True, help='Path to a CJK font for wrapping preview copy')
fontpath = parser.parse_args().font
samples={
 'classroom-game':('谁生活在海洋里？',['观察海龟的外壳','看看海豚的身体','说说自己的发现'],'先观察，再和同伴交流理由。'),
 'training-workshop':('从观察事实到支持行动',['记录儿童的原话与动作，区分事实和推断。','比较不同解释，为每种解释寻找证据。','共同提出可验证的支持行动。'],'小组讨论：下次观察哪些变化？'),
 'classroom-nature':('小种子的新发现',['看一看：叶子是什么形状？','比一比：哪一株长得更高？','说一说：还发现了什么变化？'],'一起到花园里找一找。'),
 'classroom-story':('小熊找到好朋友',['开始：小熊走进森林。','后来：听见朋友呼唤。','最后：大家分享果子。'],'想一想：小熊的心情怎样变了？'),
 'training-case':('从观察记录找到支持策略',['观察事实：孩子三次调整积木位置，仍未搭稳。','保留原话：“我想搭高一点，但是它总是倒下来。”','共同讨论：哪些材料和提问能够支持孩子继续尝试？','支持策略：补充不同形状的积木，观察儿童接下来的探索。'],'先描述看见的行为，再讨论支持方法。'),
 'training-action':('把研讨变成下一次行动',['明确问题：记录儿童在搭建中遇到的具体困难，选定本周持续观察的重点。','实施支持：补充不同形状的材料，用开放提问引导儿童尝试多种搭建方法。','收集证据：保留儿童原话与作品，对照目标进行复盘。'],'确定负责人、实施时间和可观察的变化。'),
}
def illustration(x,y,w,h,spec,key):
 # Native vector placeholder explicitly labeled as a layout example.
 a=spec['accent']; soft=spec['soft']; ink=spec['ink']
 content=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{soft}"/>'
 if key=='classroom-game':
  scene=f'<path d="M90 160Q230 30 390 160Q230 290 90 160Z" fill="{a}"/><path d="M375 160L485 80V240Z" fill="{a}"/><circle cx="167" cy="147" r="9" fill="{ink}"/><circle cx="525" cy="65" r="15" fill="none" stroke="{a}" stroke-width="5"/>'
 elif key=='classroom-nature':
  scene=f'<path d="M310 290V100" stroke="{a}" stroke-width="9" fill="none"/><path d="M309 192C215 201 198 126 204 114C278 111 314 143 309 192ZM314 148C393 159 425 88 416 75C347 80 313 100 314 148Z" fill="{a}"/><path d="M215 290H407L383 353H239Z" fill="#C89865"/><circle cx="464" cy="66" r="32" fill="#E5C780"/>'
 elif key=='classroom-story':
  scene=f'<path d="M0 230Q150 160 320 230T640 230V360H0Z" fill="{soft}"/><circle cx="279" cy="82" r="30" fill="{a}"/><circle cx="361" cy="82" r="30" fill="{a}"/><ellipse cx="320" cy="236" rx="68" ry="100" fill="{a}"/><circle cx="320" cy="132" r="66" fill="#C98965"/><ellipse cx="320" cy="158" rx="34" ry="25" fill="#F5DFC4"/><circle cx="297" cy="125" r="5" fill="{ink}"/><circle cx="343" cy="125" r="5" fill="{ink}"/><circle cx="320" cy="148" r="7" fill="{ink}"/>'
 else:
  scene=f'<rect x="90" y="45" width="460" height="280" rx="14" fill="#FFFFFF"/><path d="M145 110H490M145 165H445M145 220H470" stroke="{soft}" stroke-width="16"/><rect x="145" y="267" width="70" height="28" fill="{a}"/><rect x="240" y="240" width="70" height="55" fill="#C4AB76"/><path d="M392 250L464 295H360Z" fill="{a}"/>'
 # Fit the vector scene within each actual picture box.
 scale=min(w/640,(h-36)/360)
 content+=f'<g transform="translate({x+(w-640*scale)/2} {y+(h-36-360*scale)/2}) scale({scale})">{scene}</g>'
 label='配图示意' if w < 250 else '配图位置 · 版式示意'
 content+=f'<text x="{x+w/2}" y="{y+h-14}" text-anchor="middle" font-size="20" fill="{ink}">{label}</text>'
 return content

def text_box(element,value):
 x,y=element['position'].values(); w,h=element['size'].values(); size=element['font']['size']; lineheight=size*1.25
 font=ImageFont.truetype(fontpath,int(size)); lines=['']
 for c in value:
  if font.getlength(lines[-1]+c)>w-4: lines.append(c)
  else: lines[-1]+=c
 valign=element['alignment']['vertical']; top=y+(h-len(lines)*lineheight)/2 if valign=='middle' else y
 color=element['font']['color']; weight='700' if element['font'].get('bold') else '400'
 return f'<text fill="{color}" font-size="{size}" font-weight="{weight}">'+''.join(f'<tspan x="{x}" y="{top+size+i*lineheight}">{escape(line)}</tspan>' for i,line in enumerate(lines))+'</text>'
for key,spec in {**EDUCATION_VARIANTS, **ACTIVITY_STYLES}.items():
 template=build_activity_template(key) if key in ACTIVITY_STYLES else build_education_variant(key)
 suffix={'classroom-nature':'scene_left_3','classroom-story':'cards_3','training-case':'cards_4','training-action':'cards_3', 'classroom-game':'scene_observe_3', 'training-workshop':'scene_discuss_3'}[key]
 layout=next(x for x in template.layouts['layouts'] if x['id'].endswith(suffix))
 title,points,cue=samples[key]
 result=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720" role="img">',f'<title>{escape(spec["name"])}：版式示意</title>','<g font-family="Noto Sans CJK SC, Microsoft YaHei, sans-serif">']
 for component in layout['components']:
  for element in component['elements']:
   if element['type']=='vector':
    pts=' '.join(f'{p["x"]},{p["y"]}' for p in element['points']); color=element['fill']['color'];result.append(f'<polygon points="{pts}" fill="{color}"/>')
   elif element['type']=='image':
    result.append(illustration(*element['position'].values(),*element['size'].values(),spec,key))
   elif element['type']=='text':
    cid=component['id']; value=''.join(r['text'] for r in element['runs']) if element.get('decorative') else title if cid=='heading' else cue if cid=='invitation' else points[int(cid.split('_')[1])]
    result.append(text_box(element,value))
 result+=['</g>','</svg>']
 (API_ROOT / f'static/templates/{key}.svg').write_text('\n'.join(result))
