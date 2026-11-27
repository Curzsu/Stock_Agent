import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import type { components } from '../../shared/api/schema';
import { requestSessionWrite } from '../../shared/api/session';
import styles from './AnalysisForm.module.css';

const examples = ['茅台', '600519', '比亚迪', '宁德时代'];

function validate(query: string) {
  if (!query) return '请输入股票代码或公司名称';
  if (query.length < 2) return '请输入至少2个字符的公司名称或股票代码';
  if (/^\d+$/.test(query) && !/^\d{5,6}$/.test(query)) return '股票代码应为5-6位数字，如 600519';
  if (!/[a-zA-Z0-9\u4e00-\u9fa5]/.test(query)) return '请输入有效的公司名称或股票代码';
}

async function createAnalysis({ query, key, signal }: { query: string; key: string; signal: AbortSignal }) {
  const body: components['schemas']['AnalyzeRequest'] = { query };
  const result = await requestSessionWrite<components['schemas']['AnalysisCreated']>('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(body),
    signal,
  });
  if (typeof result?.analysis_id !== 'string' || !result.analysis_id.trim()) throw new Error('启动分析失败');
  return result.analysis_id;
}

export function AnalysisForm() {
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const pendingKey = useRef<string | undefined>(undefined);
  const navigate = useNavigate();
  const mutation = useMutation({ mutationFn: createAnalysis, retry: false });
  useEffect(() => () => request.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (request.current) return;
    const value = query.trim();
    const issue = validate(value);
    if (issue) {
      setError(issue);
      input.current?.focus();
      return;
    }
    setError('');
    const key = pendingKey.current ??= crypto.randomUUID();
    const controller = new AbortController();
    request.current = controller;
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      void Notification.requestPermission().catch(() => undefined);
    }
    try {
      const id = await mutation.mutateAsync({ query: value, key, signal: controller.signal });
      pendingKey.current = undefined;
      if (!controller.signal.aborted) {
        navigate(`/app/analysis/${encodeURIComponent(id)}`, { state: { submittedQuery: value } });
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '启动分析失败');
    } finally {
      request.current = null;
    }
  }

  return (
    <form className={styles.form} aria-label="发起股票研究" onSubmit={submit}>
      <div className={styles.wrapper}>
        <input
          ref={input}
          className={styles.input}
          aria-label="股票代码或公司名称"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'analysis-input-error' : undefined}
          autoComplete="off"
          placeholder="输入股票代码或公司名称..."
          value={query}
          onChange={(event) => { pendingKey.current = undefined; setQuery(event.target.value); setError(''); }}
          disabled={mutation.isPending}
        />
        <button className={styles.submit} type="submit" aria-label="开始分析" disabled={mutation.isPending}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="22" height="22" aria-hidden="true">
            <path d="M5 12h14" />
            <path d="m12 5 7 7-7 7" />
          </svg>
        </button>
      </div>
      <div className={styles.hints}>
        <span>示例：</span>
        {examples.map((value) => (
          <button key={value} type="button" disabled={mutation.isPending} onClick={() => {
            if (query !== value) pendingKey.current = undefined;
            setQuery(value);
            setError('');
            input.current?.focus();
          }}>{value}</button>
        ))}
      </div>
      {error && <p id="analysis-input-error" className={styles.error} role="alert">{error}</p>}
      {mutation.isPending && <p className={styles.pending} role="status">正在启动分析…</p>}
    </form>
  );
}
