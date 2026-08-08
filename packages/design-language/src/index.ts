import type { DeckDesignPlan } from "@sparkdeck/presentation-model";

export type DesignTokens={background:string;surface:string;text:string;accent:string;secondary:string;muted:string;fontFamily:string;headingWeight:number;bodyWeight:number;titlePt:number;bodyPt:number;captionPt:number;space:number;radius:number;strokeWidth:number};
const luminance=(hex:string)=>{const c=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.03928?v/12.92:((v+.055)/1.055)**2.4);return .2126*c[0]!+.7152*c[1]!+.0722*c[2]!};
export const contrast=(a:string,b:string)=>{const [hi,lo]=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (hi!+.05)/(lo!+.05)};
const readableText=(background:string,candidates:string[])=>candidates.sort((a,b)=>contrast(b,background)-contrast(a,background))[0]??"#111111";
export function resolveDesignTokens(plan:DeckDesignPlan):DesignTokens{
 const colors=plan.palette.colors,background=colors[0]!,accent=colors[1]!,secondary=colors[2]!,text=readableText(background,["#111111","#FFFFFF",...colors.slice(3)]);
 return{background,surface:colors[3]??background,text,accent,secondary,muted:colors[4]??secondary,fontFamily:"system-ui",headingWeight:plan.typography.headingWeight,bodyWeight:plan.typography.bodyWeight,titlePt:plan.densityTarget==="dense"?30:36,bodyPt:plan.densityTarget==="dense"?17:20,captionPt:15,space:plan.densityTarget==="airy"?24:16,radius:plan.shapeLanguage.cornerStyle==="round"?24:plan.shapeLanguage.cornerStyle==="soft"?10:0,strokeWidth:plan.shapeLanguage.strokeStyle==="expressive"?3:plan.shapeLanguage.strokeStyle==="subtle"?1:0};
}
export function validateTokens(tokens:DesignTokens){return{passed:contrast(tokens.text,tokens.background)>=4.5&&tokens.bodyPt>=16,contrast:contrast(tokens.text,tokens.background)}}
