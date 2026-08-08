import { DeckDesignPlanSchema,NarrativeOutlineSchema,PageDesignIntentSchema,hashContent,versioned,type DeckDesignPlan,type NarrativeOutline,type PageDesignIntent,type PresentationBrief } from "@sparkdeck/presentation-model";
import type { GenerateTextUseCase } from "../use-cases/generate-text.use-case.js";
import { AppError } from "../../shared/errors/app-error.js";

const productionLanguage=/(?:\b(?:x|y|width|height)\b|css|html|svg|tailwind|pptx|template\s*id|coordinate)/i;
const jsonOf=(content:string):any=>{try{return JSON.parse(content)}catch{throw new AppError("MODEL_JSON_INVALID","Model did not return valid JSON",502)}};
const designOutputShape={plan:{briefId:"same brief id",designSeed:"stable creative seed",tone:["descriptive tone"],typography:{character:"typographic character",headingWeight:700,bodyWeight:400},palette:{mood:"color mood",colors:["#RRGGBB","#RRGGBB","#RRGGBB"]},shapeLanguage:{character:"shape character",cornerStyle:"sharp|soft|round",strokeStyle:"none|subtle|expressive"},illustrationDirection:"optional art direction",densityTarget:"airy|balanced|dense",rhythm:{variation:"subtle|moderate|strong",continuity:["deck consistency rule"]},consistencyRules:["rule"]},intents:[{pageId:"existing page id",focalMessage:"primary communication",hierarchy:[{contentGroupId:"existing group id",priority:1}],groups:[{id:"new design group id",contentGroupIds:["existing group id"],treatment:"semantic treatment"}],relationships:[{from:"existing id",to:"existing id",kind:"sequence|contrast|supports|reveals|belongs"}],visualStrategy:"none|background|subject|evidence|gallery|diagram",balance:"symmetric|asymmetric|centered|directional",flow:"vertical|horizontal|radial|sequence|free-emphasis",density:"low|medium|high",emphasis:[{targetId:"existing id",strength:"low|medium|high",reason:"why"}],mediaRequests:[{id:"new media id",claimIds:["existing claim id"],role:"background|subject|cutout|detail|evidence",description:"visual subject and purpose",fit:"cover|contain",focalPolicy:"auto|center|face|subject",textSafeArea:"none|left|right|top|bottom|center"}],avoid:["communication risk"]}]};

export class NarrativePlanner{
 constructor(private readonly text:GenerateTextUseCase){}
 async plan(brief:PresentationBrief):Promise<NarrativeOutline>{
  const schema={pages:[{id:"string",purpose:"string",headline:"string",message:"string",contentGroups:[{id:"string",kind:"paragraph|list|comparison|sequence|quote|metric|question|answer|caption|table|chart-data|annotation",text:"string?",items:"string[]?",rows:"(string|number)[][]?",claimIds:"string[]",required:"boolean"}],speakerNotes:"string[]",evidenceRequests:"array",continuityLinks:"string[]"}]};
  const result=await this.text.execute({systemPrompt:"Return one JSON narrative outline. Describe audience-facing content only. Do not describe layouts, coordinates, templates, CSS, HTML, SVG or PPTX code.",userPrompt:JSON.stringify({brief:{title:brief.title,audience:brief.audience,ageRange:brief.ageRange,usageContext:brief.usageContext,objective:brief.objective,pageCount:brief.pageCount,constraints:brief.constraints,language:brief.language},schema}),responseFormat:"json_object"});
  if(productionLanguage.test(result.content))throw new AppError("PRODUCTION_LANGUAGE_LEAK","Narrative contains production language",422);
  const raw=jsonOf(result.content);
  return NarrativeOutlineSchema.parse(versioned({briefId:brief.id,pages:raw.pages,confirmedAt:null},0,{brief:brief.contentHash}));
 }
}

export class DesignPlanner{
 constructor(private readonly text:GenerateTextUseCase){}
 async plan(brief:PresentationBrief,outline:NarrativeOutline):Promise<{plan:DeckDesignPlan;intents:PageDesignIntent[]}>{
  const result=await this.text.execute({systemPrompt:"Return JSON design communication intent only. Use every existing page and content group exactly once or more. Never return coordinates, sizes, CSS, HTML, SVG, PPTX code, template IDs or layout IDs.",userPrompt:JSON.stringify({brief,outline,requiredOutputShape:designOutputShape}),responseFormat:"json_object"});
  if(productionLanguage.test(result.content))throw new AppError("PRODUCTION_LANGUAGE_LEAK","Design plan contains production language",422);
  const raw=jsonOf(result.content);
  const plan=DeckDesignPlanSchema.parse(versioned(raw.plan,0,{outline:outline.contentHash}));
  const intents=PageDesignIntentSchema.array().length(outline.pages.length).parse(raw.intents);
  for(const page of outline.pages){const intent=intents.find(item=>item.pageId===page.id);if(!intent)throw new AppError("DESIGN_REFERENCE_INVALID",`Missing design intent for ${page.id}`,422);const ids=new Set(page.contentGroups.map(group=>group.id));if(intent.hierarchy.some(item=>!ids.has(item.contentGroupId))||intent.groups.some(group=>group.contentGroupIds.some(id=>!ids.has(id))))throw new AppError("DESIGN_REFERENCE_INVALID",`Unknown content group on ${page.id}`,422);}
  return{plan,intents};
 }
}
export const promptHash=(value:unknown)=>hashContent({version:"007.1",value});
