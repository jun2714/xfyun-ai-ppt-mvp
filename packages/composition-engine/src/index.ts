import { hashContent, type Bounds, type CompositionCandidate, type CompositionNode, type NarrativePage, type PageDesignIntent } from "@sparkdeck/presentation-model";
import type { DesignTokens } from "@sparkdeck/design-language";

export type Canvas={width:number;height:number};
export type ResolvedCompositionNode={id:string;kind:CompositionNode["kind"];sourceIds:string[];bounds:Bounds;props:Record<string,unknown>;children:ResolvedCompositionNode[]};
export type ResolvedCandidate=CompositionCandidate&{resolved:ResolvedCompositionNode};
const node=(kind:CompositionNode["kind"],id:string,sourceIds:string[],props:Record<string,unknown>={},children?:CompositionNode[]):CompositionNode=>({kind,id,sourceIds,props,...(children?{children}:{})});
const contentNodes=(page:NarrativePage)=>page.contentGroups.map((group,index)=>node(group.kind==="chart-data"?"Chart":"Text",`${page.id}-content-${index}`, [group.id],{contentGroupId:group.id}));

export function generateCandidateTrees(page:NarrativePage,intent:PageDesignIntent):CompositionCandidate[]{
 const contents=contentNodes(page),media=intent.mediaRequests.map((request,index)=>node("Image",`${page.id}-media-${index}`,[request.id],{requestId:request.id}));
 const title=node("Text",`${page.id}-title`,[page.id],{role:"title"});
 const strategies:[CompositionCandidate["strategy"],CompositionNode][]=[
  ["content-led",node("Canvas",`${page.id}-canvas-a`,[page.id],{},[node("SafeArea",`${page.id}-safe-a`,[],{},[node("Stack",`${page.id}-stack-a`,[],{direction:"vertical"},[title,...contents,...media])])])],
  ["visual-led",node("Canvas",`${page.id}-canvas-b`,[page.id],{},[node("SafeArea",`${page.id}-safe-b`,[],{},[node("Overlay",`${page.id}-overlay-b`,[],{},[...media,node("Anchor",`${page.id}-anchor-b`,[],{anchor:"leading"},[node("Stack",`${page.id}-stack-b`,[],{direction:"vertical"},[title,...contents])])])])])],
  ["balanced",node("Canvas",`${page.id}-canvas-c`,[page.id],{},[node("SafeArea",`${page.id}-safe-c`,[],{},[title,node("Grid",`${page.id}-grid-c`,[],{columns:media.length?2:1},[node("Flow",`${page.id}-flow-c`,[],{},contents),node("Flow",`${page.id}-media-flow-c`,[],{},media)])])])]
 ];
 return strategies.map(([strategy,tree])=>({id:`cand-${hashContent({page:page.id,strategy,intent}).slice(0,12)}`,pageId:page.id,strategy,tree,score:0,hardFailures:[],scoreBreakdown:{},selected:false}));
}

const inset=(b:Bounds,p:number):Bounds=>({x:b.x+p,y:b.y+p,width:Math.max(1,b.width-p*2),height:Math.max(1,b.height-p*2)});
const split=(b:Bounds,count:number,direction:"vertical"|"horizontal",gap:number)=>Array.from({length:count},(_,i)=>direction==="vertical"?{x:b.x,y:b.y+i*(b.height-gap*(count-1))/count+i*gap,width:b.width,height:(b.height-gap*(count-1))/count}:{x:b.x+i*(b.width-gap*(count-1))/count+i*gap,y:b.y,width:(b.width-gap*(count-1))/count,height:b.height});
export function solveTree(tree:CompositionNode,canvas:Canvas,tokens:DesignTokens):ResolvedCompositionNode{
 const resolve=(current:CompositionNode,bounds:Bounds):ResolvedCompositionNode=>{
  const children=current.children??[];let boxes:Bounds[]=[];
  if(current.kind==="Canvas")boxes=children.map(()=>({x:0,y:0,width:canvas.width,height:canvas.height}));
  else if(current.kind==="SafeArea")boxes=children.map(()=>inset(bounds,Math.max(tokens.space,Math.min(canvas.width,canvas.height)*.05)));
  else if(current.kind==="Stack"||current.kind==="Flow")boxes=split(bounds,children.length,(current.props.direction as "vertical"|"horizontal")??"vertical",tokens.space);
  else if(current.kind==="Grid"){const columns=Math.max(1,Number(current.props.columns??1)),rows=Math.ceil(children.length/columns),cellW=(bounds.width-tokens.space*(columns-1))/columns,cellH=(bounds.height-tokens.space*(rows-1))/rows;boxes=children.map((_,i)=>({x:bounds.x+(i%columns)*(cellW+tokens.space),y:bounds.y+Math.floor(i/columns)*(cellH+tokens.space),width:cellW,height:cellH}));}
  else if(current.kind==="Overlay")boxes=children.map(()=>bounds);
  else if(current.kind==="Anchor"){const width=bounds.width*.58;boxes=children.map(()=>({x:current.props.anchor==="trailing"?bounds.x+bounds.width-width:bounds.x,y:bounds.y,width,height:bounds.height}));}
  else boxes=children.map(()=>bounds);
  return{id:current.id,kind:current.kind,sourceIds:current.sourceIds,bounds,props:current.props,children:children.map((child,i)=>resolve(child,boxes[i]??bounds))};
 };
 return resolve(tree,{x:0,y:0,width:canvas.width,height:canvas.height});
}
const leaves=(n:ResolvedCompositionNode):ResolvedCompositionNode[]=>n.children.length?n.children.flatMap(leaves):[n];
export function scoreCandidate(candidate:CompositionCandidate,resolved:ResolvedCompositionNode,canvas:Canvas):ResolvedCandidate{
 const items=leaves(resolved),failures:string[]=[];for(const item of items){const b=item.bounds;if(b.x<0||b.y<0||b.x+b.width>canvas.width+.01||b.y+b.height>canvas.height+.01)failures.push(`OUT_OF_BOUNDS:${item.id}`);if(b.width<1||b.height<1)failures.push(`EMPTY_BOUNDS:${item.id}`)}
 const occupied=items.reduce((sum,i)=>sum+i.bounds.width*i.bounds.height,0)/(canvas.width*canvas.height),whitespace=Math.max(0,1-Math.min(1,occupied)),hierarchy=items.length?1:0,balance=1-Math.abs(.5-(items.reduce((s,i)=>s+i.bounds.x+i.bounds.width/2,0)/Math.max(1,items.length))/canvas.width),density=1-Math.abs(.45-Math.min(1,occupied));const breakdown={hierarchy,whitespace,balance,density};const score=Object.values(breakdown).reduce((a,b)=>a+b,0)/4-(failures.length*10);
 return{...candidate,resolved,hardFailures:failures,scoreBreakdown:breakdown,score};
}
export function composePage(page:NarrativePage,intent:PageDesignIntent,canvas:Canvas,tokens:DesignTokens){const candidates=generateCandidateTrees(page,intent).map(c=>scoreCandidate(c,solveTree(c.tree,canvas,tokens),canvas)).filter(c=>!c.hardFailures.length).sort((a,b)=>b.score-a.score);if(!candidates.length)throw new Error(`No valid composition for ${page.id}`);return candidates.map((c,i)=>({...c,selected:i===0}));}
