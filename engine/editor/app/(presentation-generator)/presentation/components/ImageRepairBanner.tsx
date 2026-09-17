'use client';
import { useEffect, useRef, useState } from 'react';
import { getApiUrl, getApiErrorMessage, resolveBackendAssetUrl } from '@/utils/api';
import { getHeader } from '../../services/api/header';
import type { ImageReplacementResult } from '../utils/mergeRepairedImages';

type RepairState = {
  status: string; message: string; missing: { page: number; slot: string; reason?: string }[];
  missing_count: number; payable_count?: number; blocked_count?: number;
  processed: number; total: number; run_id: string | null;
  replaceable?: { key: string; page: number; url: string; slot: string }[];
  replacements?: ImageReplacementResult[];
};

type Props = {
  presentationId: string; disabled: boolean;
  flush: () => Promise<void>;
  onBusy: (busy: boolean) => void;
  onCompleted: (replacements?: ImageReplacementResult[]) => Promise<void>;
};

const inflight = new Set<string>();

export default function ImageRepairBanner({ presentationId, disabled, flush, onBusy, onCompleted }: Props) {
  const [state, setState] = useState<RepairState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [selected, setSelected] = useState('');
  const active = useRef(false);
  const startingRef = useRef(false);
  const processedRef = useRef(0);
  const callbacks = useRef({ onBusy, onCompleted });
  callbacks.current = { onBusy, onCompleted };
  const request = async (method = 'GET', replacement?: { key: string; expected_url: string }) => {
    const response = await fetch(getApiUrl(`/api/v1/ppt/presentation/${presentationId}/image-repair`), {
      method, headers: getHeader(), cache: 'no-store',
      ...(replacement ? { body: JSON.stringify(replacement) } : {}),
    });
    if (!response.ok) throw new Error(await getApiErrorMessage(response, '暂时无法读取补图状态'));
    return await response.json() as RepairState;
  };
  const apply = async (next: RepairState) => {
    const processed = Number(next.processed || 0);
    const finished = active.current && next.status !== 'pending';
    const progressed = processed > processedRef.current;
    processedRef.current = processed;
    if (finished || progressed) {
      await callbacks.current.onCompleted(next.replacements);
    }
    active.current = next.status === 'pending';
    if (!active.current) inflight.delete(presentationId);
    callbacks.current.onBusy(active.current);
    setState(next);
  };
  const pending = state?.status === 'pending';
  useEffect(() => {
    if (disabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request();
        if (!stopped && !startingRef.current) { await apply(next); setError(''); }
      } catch (reason) {
        if (!stopped) {
          const message = reason instanceof Error ? reason.message : '补图状态读取失败';
          setError(
            /failed to fetch|networkerror|load failed/i.test(message)
              ? '补图服务暂时连不上，正在重试，已完成的图片会保留。'
              : message,
          );
        }
      } finally {
        if (!stopped && active.current) timer = setTimeout(poll, 4000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [presentationId, disabled, pending]);
  const start = async (replace = false) => {
    if (startingRef.current || active.current || inflight.has(presentationId)) return;
    inflight.add(presentationId);
    startingRef.current = true; setStarting(true); setError('');
    let requestSent = false;
    try {
      const chosen = state?.replaceable?.find(item => item.key === selected);
      if (replace && !chosen) throw new Error('请先选择要重新生成的图片');
      await flush();
      processedRef.current = 0;
      callbacks.current.onBusy(true);
      active.current = true;
      setState(current => current ? { ...current, status: 'pending', message: '正在确认补图任务' } : current);
      requestSent = true;
      await apply(await request('POST', replace && chosen ? { key: chosen.key, expected_url: chosen.url } : undefined));
    } catch (reason) {
      active.current = requestSent;
      callbacks.current.onBusy(requestSent);
      setError(reason instanceof Error ? reason.message : '请求结果待确认，正在检查任务状态');
    } finally {
      startingRef.current = false; setStarting(false);
      if (!active.current) inflight.delete(presentationId);
    }
  };
  if (disabled || (!error && !starting && !state?.missing_count && !state?.replaceable?.length && state?.status !== 'pending')) return null;
  const pages = [...new Set(state?.missing.map(item => item.page) || [])].join('、');
  const canStart = !starting && !active.current && !!state?.missing_count;
  return <div className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-slate-800" role="status" aria-live="polite">
    <div className="min-w-0 flex-1">
      <p className="font-medium">{state?.status === 'pending' ? `正在处理图片 · 已处理 ${state.processed}/${state.total} 个请求` : state?.missing_count ? `待补图片 ${state.missing_count} 处${pages ? `（第 ${pages} 页）` : ''}` : '图片检查与单张替换'}</p>
      <p>{error || state?.message || '图片不完整或不合适时，可选择单张重新生成。新图未通过检查时保留原图。'}</p>
      {!!state?.missing.some(item => item.reason) && <details className="mt-1"><summary>查看缺图原因</summary>
        <ul>{state.missing.filter(item => item.reason).map((item, index) => <li key={index}>第 {item.page} 页：{item.reason}</li>)}</ul>
      </details>}
      {state?.status === 'pending' && <p>正在补图，完成后可继续编辑。</p>}
    </div>
    {!!state?.missing_count && <button className="border border-teal-700 bg-teal-700 px-4 py-2 text-white disabled:opacity-50" disabled={!canStart} onClick={() => void start()}>
      {starting ? '正在保存课件…' : active.current ? '正在补图…' : '补齐缺图'}
    </button>}
    {!!state?.replaceable?.length && <div className="flex items-center gap-2">
      <select aria-label="选择需要重新生成的图片" className="max-w-52 border bg-white p-2" value={selected}
        disabled={starting || active.current} onChange={event => setSelected(event.target.value)}>
        <option value="">选择要替换的图片</option>
        {state.replaceable.map((item, index, items) => <option key={item.key} value={item.key}>
          第 {item.page} 页 · 第 {items.slice(0, index + 1).filter(other => other.page === item.page).length} 张图
        </option>)}
      </select>
      {selected && <img alt="所选图片预览" className="h-12 w-16 object-contain" src={resolveBackendAssetUrl(state.replaceable.find(item => item.key === selected)?.url || '')} />}
      <button className="border border-teal-700 px-3 py-2 disabled:opacity-50" disabled={!selected || starting || active.current}
        onClick={() => void start(true)}>重新生成这张图</button>
    </div>}
  </div>;
}
