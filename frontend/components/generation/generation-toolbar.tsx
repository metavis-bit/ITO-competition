'use client';

import { useState, useRef, useMemo } from 'react';
import { Bot, Check, ChevronLeft, Globe, Paperclip, FileText, X, Globe2, ImagePlus } from 'lucide-react';
import { ImageLibraryDialog } from './image-library-dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useSettingsStore } from '@/lib/store/settings';
import { PDF_PROVIDERS } from '@/lib/pdf/constants';
import type { PDFProviderId } from '@/lib/pdf/types';
import { WEB_SEARCH_PROVIDERS } from '@/lib/web-search/constants';
import type { WebSearchProviderId } from '@/lib/web-search/types';
import type { ProviderId } from '@/lib/ai/providers';
import type { SettingsSection } from '@/lib/types/settings';
import {
  OUTPUT_ARTIFACT_TYPES,
  type OutputArtifactType,
} from '@/lib/types/output-types';
import { MediaPopover } from '@/components/generation/media-popover';

// ─── Constants ───────────────────────────────────────────────
const MAX_PDF_SIZE_MB = 50;
const MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024;

const REFERENCE_ACCEPT =
  '.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.bmp,.gif,.mp4,.mov,.mkv,.avi,.wav,.mp3,.txt,.md,.csv,.pdf';
const MAX_REFERENCE_SIZE_BYTES = 200 * 1024 * 1024;

function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
}

// ─── Types ───────────────────────────────────────────────────
// ─── Reference Purpose Types ────────────────────────────────
export type ReferencePurpose =
  | 'knowledge_content'
  | 'layout_style'
  | 'case_example'
  | 'exercise_question'
  | 'general_reference';

export const REFERENCE_PURPOSE_OPTIONS: Array<{
  value: ReferencePurpose;
  labelZh: string;
  labelEn: string;
}> = [
  { value: 'knowledge_content', labelZh: '参考知识点内容', labelEn: 'Knowledge content' },
  { value: 'layout_style', labelZh: '参考排版/格式风格', labelEn: 'Layout / style reference' },
  { value: 'case_example', labelZh: '提取案例素材', labelEn: 'Extract case / examples' },
  { value: 'exercise_question', labelZh: '参考习题/测验', labelEn: 'Exercise / quiz reference' },
  { value: 'general_reference', labelZh: '通用参考', labelEn: 'General reference' },
];

export interface GenerationToolbarProps {
  language: 'zh-CN' | 'en-US';
  onLanguageChange: (lang: 'zh-CN' | 'en-US') => void;
  webSearch: boolean;
  onWebSearchChange: (v: boolean) => void;
  onSettingsOpen: (section?: SettingsSection) => void;
  // PDF
  pdfFile: File | null;
  onPdfFileChange: (file: File | null) => void;
  // Additional reference files (Word/PPT/Image/Video/etc.)
  referenceFiles: File[];
  onReferenceFilesChange: (files: File[]) => void;
  // Per-file purpose annotation (keyed by "fileName_size")
  referencePurposes: Record<string, ReferencePurpose>;
  onReferencePurposesChange: (purposes: Record<string, ReferencePurpose>) => void;
  outputTypes: OutputArtifactType[];
  onOutputTypesChange: (types: OutputArtifactType[]) => void;
  onPdfError: (error: string | null) => void;
}

// ─── Component ───────────────────────────────────────────────
export function GenerationToolbar({
  language,
  onLanguageChange,
  webSearch,
  onWebSearchChange,
  onSettingsOpen,
  pdfFile,
  onPdfFileChange,
  referenceFiles,
  onReferenceFilesChange,
  referencePurposes,
  onReferencePurposesChange,
  outputTypes,
  onOutputTypesChange,
  onPdfError,
}: GenerationToolbarProps) {
  const { t } = useI18n();
  const currentProviderId = useSettingsStore((s) => s.providerId);
  const currentModelId = useSettingsStore((s) => s.modelId);
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const setModel = useSettingsStore((s) => s.setModel);
  const pdfProviderId = useSettingsStore((s) => s.pdfProviderId);
  const pdfProvidersConfig = useSettingsStore((s) => s.pdfProvidersConfig);
  const setPDFProvider = useSettingsStore((s) => s.setPDFProvider);
  const webSearchProviderId = useSettingsStore((s) => s.webSearchProviderId);
  const webSearchProvidersConfig = useSettingsStore((s) => s.webSearchProvidersConfig);
  const setWebSearchProvider = useSettingsStore((s) => s.setWebSearchProvider);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const referenceInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [imageLibOpen, setImageLibOpen] = useState(false);

  // Check if the selected web search provider has a valid config (API key or server-configured)
  const webSearchProvider = WEB_SEARCH_PROVIDERS[webSearchProviderId];
  const webSearchConfig = webSearchProvidersConfig[webSearchProviderId];
  const webSearchAvailable = webSearchProvider
    ? !webSearchProvider.requiresApiKey ||
      !!webSearchConfig?.apiKey ||
      !!webSearchConfig?.isServerConfigured
    : false;

  // Configured LLM providers (only those with valid credentials + models + endpoint)
  const configuredProviders = providersConfig
    ? Object.entries(providersConfig)
        .filter(
          ([, config]) =>
            (!config.requiresApiKey || config.apiKey || config.isServerConfigured) &&
            config.models.length >= 1 &&
            (config.baseUrl || config.defaultBaseUrl || config.serverBaseUrl),
        )
        .map(([id, config]) => ({
          id: id as ProviderId,
          name: config.name,
          icon: config.icon,
          isServerConfigured: config.isServerConfigured,
          models:
            config.isServerConfigured && !config.apiKey && config.serverModels?.length
              ? config.models.filter((m) => new Set(config.serverModels).has(m.id))
              : config.models,
        }))
    : [];

  const currentProviderConfig = providersConfig?.[currentProviderId];

  // PDF handler
  const handleFileSelect = (file: File) => {
    if (!isPdfFile(file)) {
      onPdfError(language === 'zh-CN' ? '仅支持 PDF 文件' : 'Only PDF files are supported');
      return;
    }
    if (file.size > MAX_PDF_SIZE_BYTES) {
      onPdfError(t('upload.fileTooLarge'));
      return;
    }
    onPdfError(null);
    onPdfFileChange(file);
  };

  const handleReferenceSelect = (files: FileList | File[]) => {
    const selected = Array.from(files);
    if (selected.length === 0) return;

    const valid = selected.filter((f) => f.size <= MAX_REFERENCE_SIZE_BYTES);
    if (valid.length !== selected.length) {
      onPdfError(
        language === 'zh-CN'
          ? '部分参考文件超过 200MB，已自动忽略'
          : 'Some reference files exceed 200MB and were skipped',
      );
    } else {
      onPdfError(null);
    }

    const merged = [...referenceFiles];
    for (const f of valid) {
      const exists = merged.some(
        (x) => x.name === f.name && x.size === f.size && x.type === f.type,
      );
      if (!exists) merged.push(f);
    }

    onReferenceFilesChange(merged);
  };
  const refFileKey = (f: File) => `${f.name}_${f.size}`;

  const removeReferenceAt = (index: number) => {
    const removed = referenceFiles[index];
    if (removed) {
      const next = { ...referencePurposes };
      delete next[refFileKey(removed)];
      onReferencePurposesChange(next);
    }
    onReferenceFilesChange(referenceFiles.filter((_, i) => i !== index));
  };

  const outputTypeMeta: Record<
    OutputArtifactType,
    { label: string; description: string }
  > = {
    pptx: {
      label: language === 'zh-CN' ? 'PPT 课件' : 'PPT Slides',
      description: language === 'zh-CN' ? '结构化演示课件 (.pptx)' : 'Structured presentation (.pptx)',
    },
    docx: {
      label: language === 'zh-CN' ? '教案' : 'Lesson Plan',
      description: language === 'zh-CN' ? '规范化教学设计方案 (.docx)' : 'Formal lesson plan (.docx)',
    },
    game_html: {
      label: language === 'zh-CN' ? '互动游戏' : 'Interactive Game',
      description:
        language === 'zh-CN' ? '趣味互动教学游戏，激发学生参与' : 'Engaging interactive mini-game (.html)',
    },
    animation_html: {
      label: language === 'zh-CN' ? '概念动画' : 'Concept Animation',
      description:
        language === 'zh-CN'
          ? '抽象知识可视化动画，降低理解门槛'
          : 'Visualize abstract concepts as animations (.html)',
    },
  };

  const outputPresets: Array<{
    id: 'fast' | 'balanced' | 'innovative';
    label: string;
    description: string;
    types: OutputArtifactType[];
  }> = [
    {
      id: 'fast',
      label: language === 'zh-CN' ? '极速备课' : 'Fast Prep',
      description: language === 'zh-CN' ? 'PPT + 教案，优先效率' : 'PPT + lesson plan for speed',
      types: ['pptx', 'docx'],
    },
    {
      id: 'balanced',
      label: language === 'zh-CN' ? '教学增强' : 'Teaching Plus',
      description:
        language === 'zh-CN' ? '增加概念动画，兼顾效率与理解' : 'Adds concept animation for clarity',
      types: ['pptx', 'docx', 'animation_html'],
    },
    {
      id: 'innovative',
      label: language === 'zh-CN' ? '创新互动' : 'Innovation Mode',
      description:
        language === 'zh-CN' ? '完整多模态输出，强化课堂互动' : 'Full multimodal output and interaction',
      types: [...OUTPUT_ARTIFACT_TYPES],
    },
  ];

  const hasSameOutputSet = (
    a: readonly OutputArtifactType[],
    b: readonly OutputArtifactType[],
  ): boolean => {
    if (a.length !== b.length) return false;
    const setA = new Set(a);
    return b.every((item) => setA.has(item));
  };

  const activeOutputPresetId =
    outputPresets.find((preset) => hasSameOutputSet(preset.types, outputTypes))?.id ?? null;

  const applyOutputPreset = (types: OutputArtifactType[]) => {
    onOutputTypesChange([...types]);
  };

  const toggleOutputType = (type: OutputArtifactType) => {
    const exists = outputTypes.includes(type);
    if (exists) {
      if (outputTypes.length <= 1) return;
      onOutputTypesChange(outputTypes.filter((v) => v !== type));
      return;
    }
    onOutputTypesChange([...outputTypes, type]);
  };
  // ─── Pill button helper ─────────────────────────────
  const pillCls =
    'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-all cursor-pointer select-none whitespace-nowrap border';
  const pillMuted = `${pillCls} border-border/50 text-muted-foreground/70 hover:text-foreground hover:bg-muted/60`;
  const pillActive = `${pillCls} border-violet-200/60 dark:border-violet-700/50 bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300`;

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {/* ── Model selector ── */}
      {configuredProviders.length > 0 ? (
        <ModelSelectorPopover
          configuredProviders={configuredProviders}
          currentProviderId={currentProviderId}
          currentModelId={currentModelId}
          currentProviderConfig={currentProviderConfig}
          setModel={setModel}
          t={t}
        />
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => onSettingsOpen('providers')}
              className={cn(
                pillCls,
                'text-amber-600 dark:text-amber-400 animate-pulse',
                'bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-950/50',
              )}
            >
              <Bot className="size-3.5" />
              <span>{t('toolbar.configureProvider')}</span>
            </button>
          </TooltipTrigger>
          <TooltipContent>{t('toolbar.configureProviderHint')}</TooltipContent>
        </Tooltip>
      )}

      {/* ── Separator ── */}
      <div className="w-px h-4 bg-border/60 mx-1" />

      {/* ── PDF (parser + upload) combined Popover ── */}
      <Popover>
        <PopoverTrigger asChild>
          {pdfFile ? (
            <button className={pillActive}>
              <Paperclip className="size-3.5" />
              <span className="max-w-[100px] truncate">{pdfFile.name}</span>
              <span
                role="button"
                className="size-4 rounded-full inline-flex items-center justify-center hover:bg-violet-200 dark:hover:bg-violet-800 transition-colors"
                onClick={(e) => {
                  e.stopPropagation();
                  onPdfFileChange(null);
                }}
              >
                <X className="size-2.5" />
              </span>
            </button>
          ) : (
            <button className={pillMuted}>
              <Paperclip className="size-3.5" />
            </button>
          )}
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-0">
          {/* Parser selector */}
          <div className="flex items-center gap-2 px-3 pt-3 pb-2">
            <span className="text-xs font-medium text-muted-foreground shrink-0">
              {t('toolbar.pdfParser')}
            </span>
            <Select value={pdfProviderId} onValueChange={(v) => setPDFProvider(v as PDFProviderId)}>
              <SelectTrigger className="h-7 text-xs flex-1 min-w-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.values(PDF_PROVIDERS).map((provider) => {
                  const cfg = pdfProvidersConfig[provider.id];
                  const available =
                    !provider.requiresApiKey || !!cfg?.apiKey || !!cfg?.isServerConfigured;
                  return (
                    <SelectItem key={provider.id} value={provider.id} disabled={!available}>
                      <div className={cn('flex items-center gap-1.5', !available && 'opacity-50')}>
                        {provider.icon && (
                          <img src={provider.icon} alt={provider.name} className="w-3.5 h-3.5" />
                        )}
                        {provider.name}
                        {cfg?.isServerConfigured && (
                          <span className="text-[9px] px-1 py-0 rounded border text-muted-foreground">
                            {t('settings.serverConfigured')}
                          </span>
                        )}
                      </div>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>

          {/* Upload area / file info */}
          <div className="px-3 pb-3">
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              accept=".pdf"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFileSelect(f);
                e.target.value = '';
              }}
            />
            {pdfFile ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <div className="size-8 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center shrink-0">
                    <FileText className="size-4 text-violet-600 dark:text-violet-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{pdfFile.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {(pdfFile.size / 1024 / 1024).toFixed(2)} MB
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => onPdfFileChange(null)}
                  className="w-full text-xs text-destructive hover:underline text-left"
                >
                  {t('toolbar.removePdf')}
                </button>
              </div>
            ) : (
              <div
                className={cn(
                  'flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors cursor-pointer',
                  isDragging
                    ? 'border-violet-400 bg-violet-50 dark:bg-violet-950/20'
                    : 'border-muted-foreground/20 hover:border-violet-300',
                )}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragging(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f) handleFileSelect(f);
                }}
              >
                <Paperclip className="size-5 text-muted-foreground/50 mb-1.5" />
                <p className="text-xs font-medium">{t('toolbar.pdfUpload')}</p>
                <p className="text-[10px] text-muted-foreground/60 mt-0.5">
                  {t('upload.pdfSizeLimit')}
                </p>
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {/* ── Additional References ── */}
      <Popover>
        <PopoverTrigger asChild>
          <button className={referenceFiles.length > 0 ? pillActive : pillMuted}>
            <Paperclip className="size-3.5" />
            {referenceFiles.length > 0 ? <span>{referenceFiles.length}</span> : null}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-3 space-y-3">
          <input
            ref={referenceInputRef}
            type="file"
            className="hidden"
            multiple
            accept={REFERENCE_ACCEPT}
            onChange={(e) => {
              if (e.target.files) handleReferenceSelect(e.target.files);
              e.target.value = '';
            }}
          />

          <button
            onClick={() => referenceInputRef.current?.click()}
            className="w-full rounded-lg border border-dashed px-3 py-2 text-xs hover:bg-muted/50"
          >
            {language === 'zh-CN' ? '添加参考资料（Word/PPT/图片/视频等）' : 'Add references (Word/PPT/Image/Video)'}
                    </button>
          <p className="text-[10px] text-muted-foreground">
            {language === 'zh-CN'
              ? '建议上传生物教材PDF、专题讲义、答案解析和教学视频，以提升生成准确性。'
              : 'Recommended: biology PDFs, handouts, answer analyses, and teaching videos.'}
          </p>

          {referenceFiles.length > 0 ? (
            <div className="max-h-64 overflow-auto space-y-2 pr-1">
              {referenceFiles.map((f, idx) => {
                const key = refFileKey(f);
                const currentPurpose = referencePurposes[key] || 'general_reference';
                return (
                  <div key={`${f.name}_${f.size}_${idx}`} className="rounded border p-2 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <FileText className="size-3.5 text-muted-foreground shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-xs truncate">{f.name}</p>
                        <p className="text-[10px] text-muted-foreground">{(f.size / 1024 / 1024).toFixed(2)} MB</p>
                      </div>
                      <button
                        onClick={() => removeReferenceAt(idx)}
                        className="size-5 inline-flex items-center justify-center rounded hover:bg-muted shrink-0"
                        aria-label="remove reference"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                    {/* Purpose selector */}
                    <Select
                      value={currentPurpose}
                      onValueChange={(v) =>
                        onReferencePurposesChange({ ...referencePurposes, [key]: v as ReferencePurpose })
                      }
                    >
                      <SelectTrigger className="h-6 text-[11px] w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {REFERENCE_PURPOSE_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {language === 'zh-CN' ? opt.labelZh : opt.labelEn}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-[11px] text-muted-foreground">{language === 'zh-CN' ? '未添加额外参考资料' : 'No additional references yet'}</p>
          )}
        </PopoverContent>
      </Popover>


      {/* ── Output Types ── */}
      <Popover>
        <PopoverTrigger asChild>
          <button
            className={
              outputTypes.length === OUTPUT_ARTIFACT_TYPES.length ? pillMuted : pillActive
            }
          >
            <FileText className="size-3.5" />
            <span>{language === 'zh-CN' ? '产物' : 'Outputs'}</span>
            <span>{outputTypes.length}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-3 space-y-3">
          <div className="space-y-1">
            <p className="text-xs font-medium text-foreground">
              {language === 'zh-CN' ? '勾选要生成的内容' : 'Select generated outputs'}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {language === 'zh-CN'
                ? '至少保留 1 项'
                : 'Keep at least one output type'}
            </p>
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium text-muted-foreground">
              {language === 'zh-CN' ? '快速模式' : 'Quick Modes'}
            </p>
            <div className="grid gap-1.5">
              {outputPresets.map((preset) => {
                const isActive = activeOutputPresetId === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => applyOutputPreset(preset.types)}
                    className={cn(
                      'w-full rounded-lg border px-2.5 py-2 text-left transition-colors',
                      isActive
                        ? 'border-violet-300 bg-violet-50/80 dark:border-violet-700 dark:bg-violet-950/30'
                        : 'border-border/60 hover:bg-muted/40',
                    )}
                  >
                    <span className="block text-xs font-medium">{preset.label}</span>
                    <span className="block text-[10px] text-muted-foreground">
                      {preset.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="h-px bg-border/60" />
          <div className="space-y-1.5">
            {OUTPUT_ARTIFACT_TYPES.map((type) => {
              const meta = outputTypeMeta[type];
              const checked = outputTypes.includes(type);
              return (
                <label
                  key={type}
                  className="flex items-start gap-2 rounded-lg border border-border/60 p-2.5 hover:bg-muted/40 cursor-pointer"
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => toggleOutputType(type)}
                    className="mt-0.5"
                  />
                  <span className="min-w-0">
                    <span className="block text-xs font-medium">{meta.label}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {meta.description}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
      {/* ── Web Search ── */}
      {webSearchAvailable ? (
        <Popover>
          <PopoverTrigger asChild>
            <button className={webSearch ? pillActive : pillMuted}>
              <Globe2 className={cn('size-3.5', webSearch && 'animate-pulse')} />
              {webSearch && (
                <span>{WEB_SEARCH_PROVIDERS[webSearchProviderId]?.name || 'Search'}</span>
              )}
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-64 p-3 space-y-3">
            {/* Toggle */}
            <button
              onClick={() => onWebSearchChange(!webSearch)}
              className={cn(
                'w-full flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-all',
                webSearch
                  ? 'bg-violet-50 dark:bg-violet-950/20 border-violet-200 dark:border-violet-800'
                  : 'border-border hover:bg-muted/50',
              )}
            >
              <Globe2
                className={cn(
                  'size-4 shrink-0',
                  webSearch ? 'text-violet-600 dark:text-violet-400' : 'text-muted-foreground',
                )}
              />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium">
                  {webSearch ? t('toolbar.webSearchOn') : t('toolbar.webSearchOff')}
                </p>
                <p className="text-[10px] text-muted-foreground/70 mt-0.5">
                  {t('toolbar.webSearchDesc')}
                </p>
              </div>
            </button>

            {/* Provider selector */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground shrink-0">
                {t('toolbar.webSearchProvider')}
              </span>
              <Select
                value={webSearchProviderId}
                onValueChange={(v) => setWebSearchProvider(v as WebSearchProviderId)}
              >
                <SelectTrigger className="h-7 text-xs flex-1 min-w-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(WEB_SEARCH_PROVIDERS).map((provider) => {
                    const cfg = webSearchProvidersConfig[provider.id];
                    const available =
                      !provider.requiresApiKey || !!cfg?.apiKey || !!cfg?.isServerConfigured;
                    return (
                      <SelectItem key={provider.id} value={provider.id} disabled={!available}>
                        <div
                          className={cn('flex items-center gap-1.5', !available && 'opacity-50')}
                        >
                          {provider.name}
                          {cfg?.isServerConfigured && (
                            <span className="text-[9px] px-1 py-0 rounded border text-muted-foreground">
                              {t('settings.serverConfigured')}
                            </span>
                          )}
                        </div>
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>
          </PopoverContent>
        </Popover>
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>
            <button className={cn(pillCls, 'text-muted-foreground/40 cursor-not-allowed')} disabled>
              <Globe2 className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>{t('toolbar.webSearchNoProvider')}</TooltipContent>
        </Tooltip>
      )}

      {/* ── Language pill ── */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={() => onLanguageChange(language === 'zh-CN' ? 'en-US' : 'zh-CN')}
            className={pillMuted}
          >
            <Globe className="size-3.5" />
            <span>{language === 'zh-CN' ? '中文' : 'EN'}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent>{t('toolbar.languageHint')}</TooltipContent>
      </Tooltip>

      {/* ── Image Library ── */}
      <Tooltip>
        <TooltipTrigger asChild>
          <button onClick={() => setImageLibOpen(true)} className={pillMuted}>
            <ImagePlus className="size-3.5" />
            <span>{language === 'zh-CN' ? '素材图库' : 'Images'}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent>{language === 'zh-CN' ? '管理教学素材图片，自动匹配到课件中' : 'Manage teaching images for slides'}</TooltipContent>
      </Tooltip>
      <ImageLibraryDialog open={imageLibOpen} onOpenChange={setImageLibOpen} />

      {/* ── Separator ── */}
      <div className="w-px h-4 bg-border/60 mx-1" />

      {/* ── Media popover ── */}
      <MediaPopover onSettingsOpen={onSettingsOpen} />
    </div>
  );
}

// ─── ModelSelectorPopover (two-level: provider → model) ─────
interface ConfiguredProvider {
  id: ProviderId;
  name: string;
  icon?: string;
  isServerConfigured?: boolean;
  models: { id: string; name: string }[];
}

function ModelSelectorPopover({
  configuredProviders,
  currentProviderId,
  currentModelId,
  currentProviderConfig,
  setModel,
  t,
}: {
  configuredProviders: ConfiguredProvider[];
  currentProviderId: ProviderId;
  currentModelId: string;
  currentProviderConfig: { name: string; icon?: string } | undefined;
  setModel: (providerId: ProviderId, modelId: string) => void;
  t: (key: string) => string;
}) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  // null = provider list, ProviderId = model list for that provider
  const [drillProvider, setDrillProvider] = useState<ProviderId | null>(null);

  const activeProvider = useMemo(
    () => configuredProviders.find((p) => p.id === drillProvider),
    [configuredProviders, drillProvider],
  );

  return (
    <Popover
      open={popoverOpen}
      onOpenChange={(open) => {
        setPopoverOpen(open);
        if (open) setDrillProvider(null);
      }}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <button
              className={cn(
                'inline-flex items-center justify-center size-7 rounded-full transition-all cursor-pointer select-none',
                'ring-1 ring-border/60 hover:ring-border hover:bg-muted/60',
                currentModelId &&
                  'ring-violet-300 dark:ring-violet-700 bg-violet-50 dark:bg-violet-950/20',
              )}
            >
              {currentProviderConfig?.icon ? (
                <img
                  src={currentProviderConfig.icon}
                  alt={currentProviderConfig.name}
                  className="size-4 rounded-sm"
                />
              ) : (
                <Bot className="size-3.5 text-muted-foreground" />
              )}
            </button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>
          {currentModelId
            ? `${currentProviderConfig?.name || currentProviderId} / ${currentModelId}`
            : t('settings.selectModel')}
        </TooltipContent>
      </Tooltip>

      <PopoverContent align="start" className="w-64 p-0">
        {/* Level 1: Provider list */}
        {!drillProvider && (
          <div className="max-h-72 overflow-y-auto">
            <div className="px-3 py-2 border-b">
              <span className="text-xs font-semibold text-muted-foreground">
                {t('toolbar.selectProvider')}
              </span>
            </div>
            {configuredProviders.map((provider) => {
              const isActive = currentProviderId === provider.id;
              return (
                <button
                  key={provider.id}
                  onClick={() => setDrillProvider(provider.id)}
                  className={cn(
                    'w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors border-b border-border/30',
                    isActive ? 'bg-violet-50/50 dark:bg-violet-950/10' : 'hover:bg-muted/50',
                  )}
                >
                  {provider.icon ? (
                    <img
                      src={provider.icon}
                      alt={provider.name}
                      className="size-5 rounded-sm shrink-0"
                    />
                  ) : (
                    <Bot className="size-5 text-muted-foreground shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{provider.name}</span>
                    {provider.isServerConfigured && (
                      <span className="text-[9px] px-1 py-0 rounded border text-muted-foreground ml-1.5">
                        {t('settings.serverConfigured')}
                      </span>
                    )}
                  </div>
                  {isActive && currentModelId && (
                    <span className="text-[10px] text-muted-foreground truncate max-w-[80px]">
                      {currentModelId}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* Level 2: Model list for selected provider */}
        {drillProvider && activeProvider && (
          <div className="max-h-72 overflow-y-auto">
            {/* Back header */}
            <button
              onClick={() => setDrillProvider(null)}
              className="w-full flex items-center gap-2 px-3 py-2 border-b bg-muted/40 hover:bg-muted/60 transition-colors"
            >
              <ChevronLeft className="size-3.5 text-muted-foreground" />
              {activeProvider.icon ? (
                <img
                  src={activeProvider.icon}
                  alt={activeProvider.name}
                  className="size-4 rounded-sm"
                />
              ) : (
                <Bot className="size-4 text-muted-foreground" />
              )}
              <span className="text-xs font-semibold">{activeProvider.name}</span>
              <span className="text-[10px] text-muted-foreground ml-auto">
                {activeProvider.models.length} {t('settings.modelCount')}
              </span>
            </button>
            {/* Models */}
            {activeProvider.models.map((model) => {
              const isSelected = currentProviderId === drillProvider && currentModelId === model.id;
              return (
                <button
                  key={model.id}
                  onClick={() => {
                    setModel(drillProvider, model.id);
                    setPopoverOpen(false);
                  }}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-2 text-left transition-colors border-b border-border/30',
                    isSelected
                      ? 'bg-violet-50 dark:bg-violet-950/20 text-violet-700 dark:text-violet-300'
                      : 'hover:bg-muted/50',
                  )}
                >
                  <span className="flex-1 truncate font-mono text-xs">{model.name}</span>
                  {isSelected && (
                    <Check className="size-3.5 shrink-0 text-violet-600 dark:text-violet-400" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}










