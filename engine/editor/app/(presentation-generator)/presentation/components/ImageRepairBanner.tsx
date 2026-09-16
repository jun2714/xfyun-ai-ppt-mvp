'use client';
import { useEffect, useRef, useState } from 'react';
import { getApiUrl, getApiErrorMessage } from '@/utils/api';
import { getHeader } from '../../services/api/header';

type RepairState = {
  status: string; message: string; missing: { page: number; slot: string }[];
  missing_count: number; payable_count?: number; blocked_count?: number;
  processed: number; total: number; run_id: string | null;
};

type Props = {
  presentationId: string; disabled: boolean;
  flush: () => Promise<void>;
  onBusy: (busy: boolean) => void;
  onCompleted: () => Promise<void>;
};

const inflight = new Set<string>();

export default function ImageRepairBanner({ presentationId, disabled, flush, onBusy, onCompleted }: Props) {
  const [state, setState] = useState<RepairState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const active = useRef(false);
  const startingRef = useRef(false);
  const processedRef = useRef(0);
  const callbacks = useRef({ onBusy, onCompleted });
  callbacks.current = { onBusy, onCompleted };
  const request = async (method = 'GET') => {
    const response = await fetch(getApiUrl(`/api/v1/ppt/presentation/${presentationId}/image-repair`), {
      method, headers: getHeader(), cache: 'no-store',
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
      await callbacks.current.onCompleted();
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
  const start = async () => {
    if (startingRef.current || active.current || inflight.has(presentationId)) return;
    inflight.add(presentationId);
    startingRef.current = true; setStarting(true); setError('');
    try {
      await flush();
      processedRef.current = 0;
      callbacks.current.onBusy(true);
      active.current = true;
      setState(current => current ? { ...current, status: 'pending', message: '正在确认补图任务' } : current);
      await apply(await request('POST'));
    } catch (reason) {
      active.current = true;
      callbacks.current.onBusy(true);
      setError(reason instanceof Error ? reason.message : '请求结果待确认，正在检查任务状态');
    } finally {
      startingRef.current = false; setStarting(false);
      if (!active.current) inflight.delete(presentationId);
    }
  };
  if (disabled || (!error && !starting && !state?.missing_count && state?.status !== 'pending')) return null;
  const pages = [...new Set(state?.missing.map(item => item.page) || [])].join('、');
  const payableCount = state?.payable_count ?? state?.missing_count ?? 0;
  const canStart = !starting && !active.current && payableCount > 0;
  return <div className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-slate-800" role="status" aria-live="polite">
    <div className="min-w-0 flex-1">
      <p className="font-medium">{state?.status === 'pending' ? `正在补图 · 已处理 ${state.processed}/${state.total} 个请求` : `待补图片 ${state?.missing_count ?? '…'} 处${pages ? `（第 ${pages} 页）` : ''}`}</p>
      <p>{error || state?.message || '已有文字和图片保留，只补齐尚未生成的图片。'}</p>
      {state?.status === 'pending' && <p>正在生成缺图，不会重复提交。关闭页面后仍会继续，回来可查看进度。</p>}
    </div>
    <button className="border border-teal-700 bg-teal-700 px-4 py-2 text-white disabled:opacity-50" disabled={!canStart} onClick={() => void start()}>
      {starting ? '正在保存课件…' : active.current ? '正在补图…' : payableCount ? '补齐缺图' : '请改提示词后再试'}
    </button>
  </div>;
}
