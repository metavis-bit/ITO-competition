'use client';

import { useState, useEffect, useRef } from 'react';
import { Upload, Search, Database, FileText, Loader2, CheckCircle2, Video, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';

/** Simulated progress hook — advances quickly at first then slows near 90% */
function useSimulatedProgress(active: boolean) {
  const [progress, setProgress] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!active) return;
    const resetTimer = setTimeout(() => setProgress(0), 0);
    let current = 0;
    const tick = () => {
      current += Math.max(0.3, (92 - current) * 0.03);
      if (current > 92) current = 92;
      setProgress(Math.round(current));
      timerRef.current = setTimeout(tick, 300);
    };
    timerRef.current = setTimeout(tick, 200);
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      clearTimeout(resetTimer);
    };
  }, [active]);

  useEffect(() => {
    if (active || progress <= 0 || progress >= 100) return;

    const completeTimer = setTimeout(() => setProgress(100), 0);
    const resetTimer = setTimeout(() => setProgress(0), 1200);
    return () => {
      clearTimeout(completeTimer);
      clearTimeout(resetTimer);
    };
  }, [active, progress]);

  return progress;
}

/** Thin progress bar */
function IngestProgressBar({ progress }: { progress: number }) {
  if (progress <= 0) return null;
  return (
    <div className="w-full mt-2">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
        <span>{progress >= 100 ? '入库完成' : '入库中...'}</span>
        <span className="tabular-nums">{progress}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300 ease-out"
          style={{
            width: `${progress}%`,
            background: progress >= 100
              ? 'linear-gradient(90deg, #34d399, #10b981)'
              : 'linear-gradient(90deg, #60a5fa, #3b82f6)',
          }}
        />
      </div>
    </div>
  );
}

export function KnowledgeBaseSettings() {
  const [queryText, setQueryText] = useState('');
  const [queryResult, setQueryResult] = useState<string | null>(null);
  const [querying, setQuerying] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestPath, setIngestPath] = useState('');
  const [uploadingFile, setUploadingFile] = useState(false);
  const [uploadingVideo, setUploadingVideo] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  const ingestProgress = useSimulatedProgress(ingesting);
  const uploadFileProgress = useSimulatedProgress(uploadingFile);
  const uploadVideoProgress = useSimulatedProgress(uploadingVideo);

  // Auto-check backend on mount
  useEffect(() => {
    fetch('/api/health', { signal: AbortSignal.timeout(3000) })
      .then((r) => setBackendOnline(r.ok))
      .catch(() => setBackendOnline(false));
  }, []);

  const handleQuery = async () => {
    if (!queryText.trim()) return;
    setQuerying(true);
    setQueryResult(null);
    try {
      const resp = await fetch('/api/knowledge/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: queryText, top_k: 5 }),
      });
      if (!resp.ok) throw new Error(`Error ${resp.status}`);
      const data = await resp.json();
      setQueryResult(
        data.answer || data.evidence?.map((e: { text: string }) => e.text).join('\n\n') || '无结果',
      );
    } catch (err) {
      toast.error('知识库查询失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setQuerying(false);
    }
  };

  const handleIngest = async () => {
    if (!ingestPath.trim()) return;
    setIngesting(true);
    try {
      const resp = await fetch('/api/knowledge/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dir_path: ingestPath, index: 'kb' }),
      });
      if (!resp.ok) throw new Error(`Error ${resp.status}`);
      toast.success('知识库入库完成');
      setIngestPath('');
    } catch (err) {
      toast.error('入库失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setIngesting(false);
    }
  };

  const handleVideoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingVideo(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch('/api/video/process', {
        method: 'POST',
        body: formData,
      });
      if (!resp.ok) throw new Error(`Error ${resp.status}`);
      const data = await resp.json();
      toast.success(
        `视频处理完成: ${data.transcript_chunks || 0} 段文字, ${data.frames || 0} 帧画面`,
      );
    } catch (err) {
      toast.error('视频处理失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setUploadingVideo(false);
      e.target.value = '';
    }
  };

  const handleRetryBackend = () => {
    setBackendOnline(null);
    fetch('/api/health', { signal: AbortSignal.timeout(3000) })
      .then((r) => setBackendOnline(r.ok))
      .catch(() => setBackendOnline(false));
  };

  return (
    <div className="space-y-8">
      {/* Backend offline warning */}
      {backendOnline === false && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/30 p-4 space-y-2">
          <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span className="text-sm font-semibold">RAG 后端服务未启动</span>
          </div>
          <div className="text-xs text-amber-600/80 dark:text-amber-400/60 space-y-1">
            <p>知识库功能需要后端服务运行。请在 <code className="px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40">backend/</code> 目录下执行：</p>
            <ol className="list-decimal list-inside space-y-0.5 ml-1">
              <li>安装依赖：<code className="px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40">pip install -r requirements.txt</code></li>
              <li>下载模型：<code className="px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40">huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3</code></li>
              <li>启动服务：<code className="px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40">uvicorn src.rag.bootstrap:create_app --factory --host 0.0.0.0 --port 9527</code></li>
            </ol>
          </div>
          <Button size="sm" variant="outline" onClick={handleRetryBackend} className="mt-1">
            重新检测
          </Button>
        </div>
      )}

      {/* Knowledge Base Query */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Search className="w-4 h-4 text-emerald-500" />
          <h3 className="text-sm font-semibold">知识库查询测试</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          输入问题测试 RAG 知识库检索效果，验证文档是否正确入库。
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
            placeholder="输入查询问题..."
            className="flex-1 px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
          />
          <Button size="sm" onClick={handleQuery} disabled={querying || !queryText.trim()}>
            {querying ? <Loader2 className="w-4 h-4 animate-spin" /> : '查询'}
          </Button>
        </div>
        {queryResult && (
          <div className="p-3 bg-muted/50 rounded-lg text-sm whitespace-pre-wrap max-h-60 overflow-y-auto">
            {queryResult}
          </div>
        )}
      </section>

      {/* Document Ingestion */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-blue-500" />
          <h3 className="text-sm font-semibold">文档入库</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          指定服务器上的文档目录路径，解析并入库到向量数据库（支持
          PDF、Word、PPT、图片、音频、视频）。
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={ingestPath}
            onChange={(e) => setIngestPath(e.target.value)}
            placeholder="输入文档目录路径，如 /data/docs"
            className="flex-1 px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={handleIngest}
            disabled={ingesting || !ingestPath.trim()}
          >
            {ingesting ? <Loader2 className="w-4 h-4 animate-spin" /> : '开始入库'}
          </Button>
        </div>
        <IngestProgressBar progress={ingestProgress} />
      </section>

      {/* File Upload */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Upload className="w-4 h-4 text-green-500" />
          <h3 className="text-sm font-semibold">上传参考文件</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          上传本地文件作为参考资料（PDF、Word、PPT、图片等），自动解析并入库。
          <br />
          也可在首页生成课件时直接上传。
        </p>
        <label className="inline-flex items-center gap-2 px-4 py-2 text-sm border rounded-lg cursor-pointer hover:bg-muted/50 transition-colors">
          <FileText className="w-4 h-4" />
          <span>选择文件上传</span>
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt,.md,.html,.png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setUploadingFile(true);
              const formData = new FormData();
              formData.append('file', file);
              formData.append('index', 'kb');
              try {
                const resp = await fetch('/api/references/upload', {
                  method: 'POST',
                  body: formData,
                });
                if (!resp.ok) {
                  if (resp.status === 502 || resp.status === 503) throw new Error('后端服务未启动，请先启动 RAG 后端');
                  throw new Error(`Error ${resp.status}`);
                }
                toast.success(`文件 "${file.name}" 上传并入库成功`);
              } catch (err) {
                toast.error(
                  '上传失败: ' + (err instanceof Error ? err.message : '未知错误'),
                );
              } finally {
                setUploadingFile(false);
              }
              e.target.value = '';
            }}
          />
        </label>
        <IngestProgressBar progress={uploadFileProgress} />
      </section>

      {/* Video Processing */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Video className="w-4 h-4 text-orange-500" />
          <h3 className="text-sm font-semibold">教学视频分析</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          上传教学视频，自动执行 ASR 语音转文字 + 关键帧提取 + VLM
          画面理解，结果入库供后续生成使用。
        </p>
        <label
          className={`inline-flex items-center gap-2 px-4 py-2 text-sm border rounded-lg transition-colors ${
            uploadingVideo ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-muted/50'
          }`}
        >
          {uploadingVideo ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Video className="w-4 h-4" />
          )}
          <span>{uploadingVideo ? '视频处理中...' : '上传教学视频'}</span>
          <input
            type="file"
            className="hidden"
            accept=".mp4,.mov,.mkv,.avi,.webm"
            disabled={uploadingVideo}
            onChange={handleVideoUpload}
          />
        </label>
        <IngestProgressBar progress={uploadVideoProgress} />
      </section>

      {/* Backend Status */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          <h3 className="text-sm font-semibold">后端服务状态</h3>
        </div>
        <BackendHealthCheck />
      </section>
    </div>
  );
}

function BackendHealthCheck() {
  const [status, setStatus] = useState<'idle' | 'checking' | 'ok' | 'error'>('idle');

  const check = async () => {
    setStatus('checking');
    try {
      const resp = await fetch('/api/health');
      if (resp.ok) {
        setStatus('ok');
      } else {
        setStatus('error');
      }
    } catch {
      setStatus('error');
    }
  };

  return (
    <div className="flex items-center gap-3">
      <Button size="sm" variant="outline" onClick={check} disabled={status === 'checking'}>
        {status === 'checking' ? <Loader2 className="w-4 h-4 animate-spin" /> : '检查连接'}
      </Button>
      {status === 'ok' && (
        <span className="text-xs text-emerald-600 flex items-center gap-1">
          <CheckCircle2 className="w-3.5 h-3.5" /> 后端服务正常
        </span>
      )}
      {status === 'error' && (
        <span className="text-xs text-red-500">后端服务不可用，请检查 BACKEND_URL 配置</span>
      )}
    </div>
  );
}
