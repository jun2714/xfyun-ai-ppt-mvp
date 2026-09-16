'use client';
import { useEffect, useRef, useState } from 'react';
import { getApiUrl, getApiErrorMessage } from '@/utils/api';
import { getHeader } from '../../services/api/header';

type RepairState = {
  status: string; message: string; missing: { page: number; slot: string }[];
  missing_count: number; processed: number; total: number; run_id: string | null;
};

type Props = {
  presentationId: string; disabled: boolean;
  flush: () => Promise<void>;
  onBusy: (busy: boolean) => void;
  onCompleted: () => Promise<void>;
};

export default function ImageRepairBanner({ presentationId, disabled, flush, onBusy, onCompleted }: Props) {
  const [state, setState] = useState<RepairState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const active = useRef(false);
  const startingRef = useRef(false);
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
    if (active.current && next.status !== 'pending') {
      // Keep editing paused until images have merged successfully. A failed fetch
      // is retried by polling, not followed by another paid generation request.
      await callbacks.current.onCompleted();
    }
    active.current = next.status === 'pending';
    callbacks.current.onBusy(active.current);
    setState(next);
  };
  useEffect(() => {
    if (disabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request();
        if (!stopped && !startingRef.current) { await apply(next); setError(''); }
      } catch (reason) {
        if (!stopped) setError(reason instanceof Error ? reason.message : '补图状态读取失败');
      } finally {
        if (!stopped && active.current) timer = setTimeout(poll, 2500);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [presentationId, disabled, state?.status]);
  const start = async () => {
    if (startingRef.current || active.current) return;
    startingRef.current = true; setStarting(true); setError('');
    try {
      await flush();
      callbacks.current.onBusy(true);
      active.current = true;
      setState(current => current ? { ...current, status: 'pending', message: '正在确认补图任务' } : current);
      await apply(await request('POST'));
    } catch (reason) {
      // POST may have reached the server despite a lost response. Poll status
      // before another click; never automatically repeat the POST.
      active.current = true;
      callbacks.current.onBusy(true);
      setError(reason instanceof Error ? reason.message : '请求结果待确认，正在检查任务状态');
    } finally {
      startingRef.current = false; setStarting(false);
    }
  };
  if (disabled || (!error && !starting && !state?.missing_count && state?.status !== 'pending')) return null;
  const pages = [...new Set(state?.missing.map(item => item.page) || [])].join('、');
  return <div className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-slate-800" role="status" aria-live="polite">
    <div className="min-w-0 flex-1">
      <p className="font-medium">{state?.status === 'pending' ? `正在补图 · 已处理 ${state.processed}/${state.total} 个请求` : `待补图片 ${state?.missing_count ?? '…'} 处${pages ? `（第 ${pages} 页）` : ''}`}</p>
      <p>{error || state?.message || '已有文字和图片保留，只补齐尚未生成的图片。'}</p>
      {state?.status === 'pending' && <p>请求可能正在排队或等待生图服务返回。关闭页面后仍会继续，回来可查看进度。</p>}
    </div>
    <button className="border border-teal-700 bg-teal-700 px-4 py-2 text-white disabled:opacity-50" disabled={starting || active.current || !state?.missing_count} onClick={() => void start()}>
      {starting ? '正在保存课件…' : active.current ? '正在补图…' : '补齐缺图'}
    </button>
  </div>;
}
