import React, { useState } from "react";
import type { ScenePage } from "../../entities/types";

type DragState = { id: string; startX: number; startY: number; dx: number; dy: number };

export function SceneCanvas({ page, selectedId, onSelect, onMove, scale = 1 }: { page: ScenePage; selectedId?: string; onSelect?: (id: string) => void; onMove?: (id: string, x: number, y: number) => void; scale?: number }) {
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
          transform: drag?.id === node.id ? `translate(${drag.dx}px, ${drag.dy}px)` : undefined
        };
        return <div key={node.id} role="button" tabIndex={0} aria-label={`${node.kind} element`}
          onPointerDown={(event) => { if (!onMove) return; event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); onSelect?.(node.id); setDrag({ id: node.id, startX: event.clientX, startY: event.clientY, dx: 0, dy: 0 }); }}
          onPointerMove={(event) => setDrag((current) => current?.id === node.id ? { ...current, dx: (event.clientX - current.startX) / scale, dy: (event.clientY - current.startY) / scale } : current)}
          onPointerUp={(event) => { if (!drag || drag.id !== node.id) return; event.currentTarget.releasePointerCapture(event.pointerId); const { dx, dy } = drag; setDrag(undefined); if (Math.abs(dx) + Math.abs(dy) > 1) onMove?.(node.id, node.bounds.x + dx, node.bounds.y + dy); }}
          onClick={(event) => { event.stopPropagation(); onSelect?.(node.id); }} className={`scene-node scene-${node.kind} ${selectedId === node.id ? "is-selected" : ""}`} style={style}>
          {node.kind === "text" ? String(node.content.text ?? "") : null}
          {node.kind === "image" && node.content.url ? <img src={String(node.content.url)} alt={String(node.content.alt ?? "")} style={{ objectFit: node.content.fit === "contain" ? "contain" : "cover" }} /> : null}
          {node.kind === "image" && !node.content.url ? <span className="media-placeholder"><b>图片待解析</b><small>{String(node.content.alt ?? "")}</small></span> : null}
          {node.kind === "chart" ? <span className="chart-placeholder">可编辑图表</span> : null}
        </div>;
      })}
    </div>
  </div>;
}
