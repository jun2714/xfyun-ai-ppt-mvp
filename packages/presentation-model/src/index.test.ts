import assert from "node:assert/strict";
import test from "node:test";
import { PageDesignIntentSchema, NarrativePageSchema } from "./index.js";

test("narrative page preserves multiple content groups",()=>{
 const page=NarrativePageSchema.parse({id:"p",purpose:"teach",headline:"h",message:"m",contentGroups:[{id:"g1",kind:"paragraph",text:"a"},{id:"g2",kind:"annotation",text:"b"},{id:"g3",kind:"annotation",text:"c"},{id:"g4",kind:"annotation",text:"d"},{id:"g5",kind:"caption",text:"e"}],speakerNotes:[],evidenceRequests:[]});
 assert.equal(page.contentGroups.length,5);
});
test("design intent rejects coordinate and template language",()=>{
 const base={pageId:"p",focalMessage:"m",hierarchy:[{contentGroupId:"g",priority:1}],groups:[{id:"d",contentGroupIds:["g"],treatment:"plain"}],relationships:[],visualStrategy:"none",balance:"centered",flow:"vertical",density:"low",emphasis:[],mediaRequests:[],avoid:[]};
 assert.equal(PageDesignIntentSchema.safeParse({...base,avoid:["templateId=hero"]}).success,false);
});
