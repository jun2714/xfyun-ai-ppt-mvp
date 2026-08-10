import React, { useState } from "react";
import type { ScenePage } from "../../entities/types";

type DragState = { id: string; mode: "move" | "resize"; startX: number; startY: number; dx: number; dy: number };

export function SceneCanvas({ page, selectedId, selectedIds = [], onSelect, onMove, onResize, scale = 1 }: { page: ScenePage; selectedId?: string; selectedIds?: string[]; onSelect?: (id: string, additive: boolean) => void; onMove?: (id: string, x: number, y: number) => void; onResize?: (id: string, width: number, height: number) => void; scale?: number }) {
  const [drag, setDrag] = useState<DragState>();
  return <div className="slide-frame" style={{ width: page.width * scale, height: page.height * scale }}>
    <div className="slide-canvas" style={{ width: page.width, height: page.height, background: page.background, transform: `scale(${scale})` }}>
      {page.nodes.map((node) => {
        const style: React.CSSProperties = {
          left: node.bounds.x, top: node.bounds.y, width: node.bounds.width, height: node.bounds.height, zIndex: node.zIndex,
          color: String(node.style.color ?? "#111111"), fontFamily: String(node.style.fontFamily ?? "Microsoft YaHei"),
          fontSize: Number(node.style.fontSize ?? 18), fontWeight: Number(node.style.fontWeight ?? 400),
          textAlign: node.style.align === "center" ? "center" : node.style.align === "right" ? "right" : "left",
          background: node.kind === "shape" ? String(node.style.fill ?? "transparent") : undefined,
          opacity: node.kind === "shape" ? Number(node.style.opacity ?? 1) : 1,
          borderRadius: Number(node.style.radius ?? 0),
          transform: `${drag?.id === node.id && drag.mode === "move" ? `translate(${drag.dx}px, ${drag.dy}px) ` : ""}rotate(${Number(node.style.rotation ?? 0)}deg)`, transformOrigin: "center"
        };
        return <div key={node.id} role="button" tabIndex={0} aria-label={`${node.kind} element`}
          onPointerDown={(event) => { if (!onMove || node.locked) return; event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); onSelect?.(node.id, event.shiftKey); setDrag({ id: node.id, mode: "move", startX: event.clientX, startY: event.clientY, dx: 0, dy: 0 }); }}
          onPointerMove={(event) => setDrag((current) => current?.id === node.id ? { ...current, dx: (event.clientX - current.startX) / scale, dy: (event.clientY - current.startY) / scale } : current)}
          onPointerUp={(event) => { if (!drag || drag.id !== node.id || drag.mode !== "move") return; event.currentTarget.releasePointerCapture(event.pointerId); const { dx, dy } = drag; setDrag(undefined); if (Math.abs(dx) + Math.abs(dy) > 1) onMove?.(node.id, node.bounds.x + dx, node.bounds.y + dy); }}
          onClick={(event) => { event.stopPropagation(); onSelect?.(node.id, event.shiftKey); }} className={`scene-node scene-${node.kind} ${selectedIds.includes(node.id) || selectedId === node.id ? "is-selected" : ""}`} style={style}>
          {node.kind === "text" ? String(node.content.text ?? "") : null}
          {node.kind === "image" && (node.content.url || node.content.dataUri) ? <img src={String(node.content.url ?? node.content.dataUri)} alt={String(node.content.alt ?? "")} style={{ objectFit: node.content.fit === "contain" ? "contain" : "cover" }} /> : null}
          {node.kind === "image" && !node.content.url && !node.content.dataUri ? <span className="media-placeholder"><b>图片待解析</b></span> : null}
          {node.kind === "chart" ? <span className="chart-placeholder">可编辑图表</span> : null}
          {node.kind === "connector" ? <svg width="100%" height="100%" aria-hidden="true"><defs><marker id={`arrow-${node.id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill={String(node.style.stroke ?? "#333333")} /></marker></defs><line x1={node.content.flipH ? "100%" : "0%"} y1={node.content.flipV ? "100%" : "0%"} x2={node.content.flipH ? "0%" : "100%"} y2={node.content.flipV ? "0%" : "100%"} stroke={String(node.style.stroke ?? "#333333")} strokeWidth={Number(node.style.strokeWidth ?? 1.5)} markerEnd={`url(#arrow-${node.id})`} /></svg> : null}
          {selectedId === node.id && onResize && !node.locked ? <span className="resize-handle" onPointerDown={(event) => { event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ id: node.id, mode: "resize", startX: event.clientX, startY: event.clientY, dx: 0, dy: 0 }); }} onPointerMove={(event) => setDrag((current) => current?.id === node.id && current.mode === "resize" ? { ...current, dx: (event.clientX - current.startX) / scale, dy: (event.clientY - current.startY) / scale } : current)} onPointerUp={(event) => { if (!drag || drag.id !== node.id || drag.mode !== "resize") return; event.currentTarget.releasePointerCapture(event.pointerId); const { dx, dy } = drag; setDrag(undefined); onResize(node.id, Math.max(8, node.bounds.width + dx), Math.max(8, node.bounds.height + dy)); }} /> : null}
        </div>;
      })}
    </div>
  </div>;
}
