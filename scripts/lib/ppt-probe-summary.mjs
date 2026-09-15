// Only fixed labels and counts may leave a private runner. Never copy log text,
// lesson copy, URLs, file paths, screenshots, traces or provider responses.
const TEMPLATE_IDS = new Set([
  'kindergarten-classroom', 'teacher-training', 'classroom-nature',
  'classroom-story', 'training-case', 'training-action',
]);
const count = (value) => Array.isArray(value) ? value.length : 0;
const QUALITY_CODES = [
  'game-contract-missing', 'question-reveals-answer', 'reveal-slide-missing',
  'reveal-before-question', 'question-slide-missing', 'topic-replaced-by-unrequested-storyline',
  'asset-caption-mismatch', 'required-asset-missing', 'asset-semantic-too-vague',
  'reveal-answer-missing', 'answer-key-missing', 'options-too-few', 'answer-not-in-options',
  'answer-map-missing', 'sequence-order-missing', 'reveal-answer-mismatch',
];
export function summarizeProbe(diagnostics) {
  const d = diagnostics && typeof diagnostics === 'object' ? diagnostics : {};
  const raw = String(d.outlineFailure?.state === 'failed' && d.outlineFailure.detail
    ? d.outlineFailure.detail : d.fatalError?.message || '');
  const selected = d.finalPresentation?.generation_metadata?.selected_template;
  let failureCode = 'NONE';
  if (d.result?.state !== 'passed') {
    failureCode = /timed?\s*out|timeout|超时/i.test(raw) ? 'TIMEOUT'
      : /schema|ValidationError|validation.*slide_type|slide_type.*validation/i.test(raw) ? 'SCHEMA'
      : /质检失败|KindergartenPlanningQualityError/i.test(raw) ? 'QUALITY'
      : /放不下|放不进|大字号|compatible.*layout|capacity/i.test(raw) ? 'CAPACITY'
      : /image|图片|配图/i.test(raw) ? 'IMAGE'
      : 'OTHER';
  }
  return {
    state: d.result?.state === 'passed' ? 'passed' : 'failed',
    stage: d.finalPresentation ? 'render' : d.outline ? 'generation' : 'outline',
    failureCode,
    qualityCodes: failureCode === 'QUALITY' ? QUALITY_CODES.filter(code => raw.includes(code)) : [],
    selectedTemplate: TEMPLATE_IDS.has(selected) ? selected : 'unknown',
    slideCount: count(d.finalPresentation?.slides),
    generationStreams: count(d.streamRequests),
    checkedImages: count(d.imageChecks),
    unresolvedImages: count(d.unresolvedImageSlots),
    textOverflows: count(d.layoutOverflows),
    smallText: count(d.unreadableAudienceText),
    mappingErrors: count(d.classroomMappingErrors),
    validationErrors: count(d.validationErrors),
  };
}
