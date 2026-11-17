/** Translate saved diagnostics at display time, including older projects. */
export function teacherReviewMessages(warning?: string | null): string[] {
  if (!warning?.trim()) return [];
  const details = warning.replace(/^大纲已保存，部分硬性校验未通过，请核对后再生成课件[。]?/, "");
  const messages = details.split(/[；\n]+/).map((part) => {
    const page = part.match(/第\s*(\d+)\s*页[：:]/);
    const prefix = page ? `第 ${page[1]} 页：` : "";
    let text = part.replace(/^\s*第\s*\d+\s*页[：:]\s*/, "").trim();
    if (!text) return "";
    if (/必须先锁定 answer_key/.test(text)) {
      text = "请补充猜测或选择活动的正确答案。";
    } else if (/answer_key 必须对应/.test(text)) {
      text = "正确答案与选项没有对应，请核对答案和选项。";
    } else if (/必须提供 answer_map/.test(text)) {
      text = "请补充配对或分类活动中每个对象的正确对应关系。";
    } else if (/sequence_order/.test(text)) {
      text = "请补充排序活动的完整正确顺序。";
    } else {
      text = text.replace(/活动\s+[A-Za-z][\w.-]*\s*/g, "本活动");
      // Unknown diagnostics must not expose internal keys, codes or identifiers.
      if (/[A-Za-z_]/.test(text)) {
        text = "活动内容需要进一步核对，请检查题目、答案和图片是否对应。";
      }
    }
    return prefix + text;
  }).filter(Boolean);
  return [...new Set(messages.length ? messages : ["请核对活动内容后再生成课件。"])];
}
