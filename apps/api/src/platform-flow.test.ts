import assert from "node:assert/strict";import test from "node:test";
import { versioned,type DeckDesignPlan,type NarrativeOutline,type PageDesignIntent,type PresentationBrief } from "@sparkdeck/presentation-model";
import { PresentationPlatformService } from "./application/services/presentation-platform.service.js";

const page={id:"page-a",purpose:"explain",headline:"A clear idea",message:"One message",contentGroups:[{id:"group-a",kind:"paragraph" as const,text:"Audience-facing content",claimIds:[],required:true},{id:"group-b",kind:"annotation" as const,text:"Supporting annotation",claimIds:[],required:true}],speakerNotes:[],evidenceRequests:[],continuityLinks:[]};
const outline=(brief:PresentationBrief):NarrativeOutline=>versioned({briefId:brief.id,pages:[page],confirmedAt:null},0,{brief:brief.contentHash});
const plan=(brief:PresentationBrief):DeckDesignPlan=>versioned({briefId:brief.id,designSeed:"seed",tone:["warm"],typography:{character:"friendly",headingWeight:700,bodyWeight:400},palette:{mood:"bright",colors:["#FFF8EB","#4F9C67","#F28C45","#FFFFFF","#767676"]},shapeLanguage:{character:"soft",cornerStyle:"round",strokeStyle:"subtle"},illustrationDirection:"consistent editorial illustration",densityTarget:"airy",rhythm:{variation:"moderate",continuity:["consistent color"]},consistencyRules:["one focal message"]});
const intent:PageDesignIntent={pageId:"page-a",focalMessage:"One message",hierarchy:[{contentGroupId:"group-a",priority:1},{contentGroupId:"group-b",priority:2}],groups:[{id:"design-group",contentGroupIds:["group-a","group-b"],treatment:"clear hierarchy"}],relationships:[],visualStrategy:"subject",balance:"asymmetric",flow:"horizontal",density:"low",emphasis:[],mediaRequests:[{id:"media-a",claimIds:[],role:"subject",description:"supporting subject",fit:"contain",focalPolicy:"subject"}],avoid:[]};
test("full flow delays images until selected composition and keeps three candidates",async()=>{
 let imageCalls=0;const narrative={plan:async(brief:PresentationBrief)=>outline(brief)} as any,designer={plan:async(brief:PresentationBrief)=>({plan:plan(brief),intents:[intent]})} as any,image={execute:async()=>{imageCalls++;return{model:"fake",url:"https://example.test/image.png",estimatedCostRmb:0}}} as any,service=new PresentationPlatformService(narrative,designer,image);
 const brief=service.create({title:"Unknown subject",audience:"learners",usageContext:"classroom",objective:"understand",pageCount:1,constraints:[],sourceAssetIds:[],language:"en"});
 const generatedOutline=outline(brief);service.saveOutline(brief.id,generatedOutline,0);service.confirmOutline(brief.id,1);service.startDesign(brief.id);await new Promise(resolve=>setTimeout(resolve,0));service.compose(brief.id,{width:960,height:540});const state=service.get(brief.id);
 assert.equal(imageCalls,0);assert.equal(state.candidates?.[0]?.length,3);assert.equal(state.outline?.pages[0]?.contentGroups.length,2);assert.ok(state.scene);
 await service.resolveAssets(brief.id);assert.equal(imageCalls,1);assert.equal(state.assetPlan?.resolvedAssetIds.length,1);
 service.quality(brief.id);assert.equal(state.quality?.passed,true);
});
