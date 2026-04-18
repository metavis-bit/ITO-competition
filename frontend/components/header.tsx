'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Archive,
  ArrowLeft,
  Download,
  ExternalLink,
  FileDown,
  Film,
  History,
  Loader2,
  MessageSquarePlus,
  Monitor,
  Moon,
  Package,
  Settings,
  Sun,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useTheme } from '@/lib/hooks/use-theme';
import { useSettingsStore } from '@/lib/store/settings';
import { useStageStore } from '@/lib/store/stage';
import { useMediaGenerationStore } from '@/lib/store/media-generation';
import { useExportPPTX } from '@/lib/export/use-export-pptx';
import { SettingsDialog } from './settings';
import {
  buildArtifactDownloadUrl,
  buildArtifactPreviewUrl,
  buildBackendCoursewareScenes,
  buildBackendStagePatch,
  getArtifactDisplayLabel,
  isBackendCoursewareContent,
} from '@/lib/backend-courseware-scenes';

interface HeaderProps {
  readonly currentSceneTitle: string;
}

type RefineTargetType = 'pptx' | 'docx' | 'game_html' | 'animation_html';

type VersionSummary = {
  version_id: string;
  created_at?: string;
  description?: string;
  version_note?: string;
};

function buildVersionedUrl(baseUrl: string, versionId?: string): string {
  if (!versionId) {
    return baseUrl;
  }
  const joiner = baseUrl.includes('?') ? '&' : '?';
  return `${baseUrl}${joiner}version_id=${encodeURIComponent(versionId)}`;
}

export function Header({ currentSceneTitle }: HeaderProps) {
  const router = useRouter();
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection] = useState<import('@/lib/types/settings').SettingsSection | undefined>(
    undefined,
  );
  const [languageOpen, setLanguageOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [refineOpen, setRefineOpen] = useState(false);
  const [refineFeedback, setRefineFeedback] = useState('');
  const [refineTargetTypes, setRefineTargetTypes] = useState<RefineTargetType[]>([
    'pptx',
    'docx',
  ]);
  const [refining, setRefining] = useState(false);

  const currentModelId = useSettingsStore((s) => s.modelId);
  const needsSetup = !currentModelId;

  const { exporting: isExporting, exportPPTX, exportResourcePack } = useExportPPTX();
  const stage = useStageStore((s) => s.stage);
  const scenes = useStageStore((s) => s.scenes);
  const generatingOutlines = useStageStore((s) => s.generatingOutlines);
  const failedOutlines = useStageStore((s) => s.failedOutlines);
  const mediaTasks = useMediaGenerationStore((s) => s.tasks);

  const backendSessionId = (stage?.backendSessionId || '').trim();
  const backendVersionId = (stage?.backendVersionId || '').trim();
  const backendArtifacts = stage?.backendArtifacts || [];
  const backendMissingArtifacts = stage?.backendMissingArtifacts;
  const backendErrors = stage?.backendErrors || [];
  const defaultRefineTargetTypes = useMemo(() => {
    const generated = backendArtifacts
      .filter((artifact) => !artifact.error && artifact.file_path)
      .map((artifact) => artifact.type)
      .filter(
        (type): type is RefineTargetType =>
          type === 'pptx' ||
          type === 'docx' ||
          type === 'game_html' ||
          type === 'animation_html',
      );
    if (generated.length > 0) {
      return generated;
    }
    const fromStage = (stage?.outputTypes || []).filter(
      (type): type is RefineTargetType =>
        type === 'pptx' ||
        type === 'docx' ||
        type === 'game_html' ||
        type === 'animation_html',
    );
    return fromStage.length > 0 ? fromStage : (['pptx', 'docx'] as RefineTargetType[]);
  }, [backendArtifacts, stage?.outputTypes]);

  const displayArtifacts = useMemo(
    () => backendArtifacts.filter((artifact) => !artifact.error && artifact.file_path),
    [backendArtifacts],
  );
  const missingArtifactTypes = useMemo(
    () => [
      ...(backendMissingArtifacts?.required || []),
      ...(backendMissingArtifacts?.optional || []),
    ],
    [backendMissingArtifacts],
  );

  const canLocalExport =
    scenes.length > 0 &&
    generatingOutlines.length === 0 &&
    failedOutlines.length === 0 &&
    Object.values(mediaTasks).every((task) => task.status === 'done' || task.status === 'failed');
  const canBackendExport = !!backendSessionId;
  const canExport = canLocalExport || canBackendExport;

  const languageRef = useRef<HTMLDivElement>(null);
  const themeRef = useRef<HTMLDivElement>(null);
  const exportRef = useRef<HTMLDivElement>(null);

  const openArtifact = useCallback(
    (artifactType: string) => {
      if (!backendSessionId) {
        toast.error(t('export.backendSessionMissing'));
        return;
      }
      const previewableTypes = new Set(['pptx', 'docx', 'game_html', 'animation_html']);
      const url = previewableTypes.has(artifactType)
        ? buildArtifactPreviewUrl(backendSessionId, artifactType, backendVersionId)
        : buildArtifactDownloadUrl(backendSessionId, artifactType, backendVersionId);
      window.open(url, '_blank');
    },
    [backendSessionId, backendVersionId, t],
  );

  const handleOutsideClick = useCallback(
    (event: MouseEvent) => {
      const target = event.target as Node;
      if (languageOpen && languageRef.current && !languageRef.current.contains(target)) {
        setLanguageOpen(false);
      }
      if (themeOpen && themeRef.current && !themeRef.current.contains(target)) {
        setThemeOpen(false);
      }
      if (exportMenuOpen && exportRef.current && !exportRef.current.contains(target)) {
        setExportMenuOpen(false);
      }
    },
    [exportMenuOpen, languageOpen, themeOpen],
  );

  useEffect(() => {
    if (!languageOpen && !themeOpen && !exportMenuOpen) {
      return;
    }
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [exportMenuOpen, handleOutsideClick, languageOpen, themeOpen]);

  const openVersionHistory = useCallback(async () => {
    setVersionHistoryOpen(true);
    if (!backendSessionId) {
      setVersions([]);
      toast.error(t('export.backendSessionMissing'));
      return;
    }
    try {
      const resp = await fetch(`/api/versions?sessionId=${encodeURIComponent(backendSessionId)}`);
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      setVersions(Array.isArray(data.versions) ? data.versions : []);
    } catch {
      // ignore
    }
  }, [backendSessionId, t]);

  const applyRollbackResult = useCallback((data: unknown) => {
    if (!isBackendCoursewareContent(data)) {
      return;
    }
    const store = useStageStore.getState();
    const currentStage = store.stage;
    if (!currentStage) {
      return;
    }
    const rollbackScenes = buildBackendCoursewareScenes(data, currentStage.id);
    const nextStage = {
      ...currentStage,
      ...buildBackendStagePatch(data),
      updatedAt: Date.now(),
    };
    store.setStage(nextStage);
    store.setScenes(rollbackScenes);
    store.setCurrentSceneId(rollbackScenes[0]?.id || null);
  }, []);

  const rollbackVersion = useCallback(
    async (versionId: string) => {
      if (!backendSessionId) {
        toast.error(t('export.backendSessionMissing'));
        return;
      }
      try {
        const resp = await fetch('/api/versions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: backendSessionId,
            version_id: versionId,
          }),
        });
        if (!resp.ok) {
          toast.error(t('export.rollbackFailed'));
          return;
        }
        const data = await resp.json();
        applyRollbackResult(data);
        toast.success(t('export.rollbackSuccess'));
        setVersionHistoryOpen(false);
      } catch {
        toast.error(t('export.rollbackFailed'));
      }
    },
    [applyRollbackResult, backendSessionId, t],
  );

  const submitRefine = useCallback(async () => {
    if (!backendSessionId) {
      toast.error(t('export.backendSessionMissing'));
      return;
    }
    if (!refineFeedback.trim() || refineTargetTypes.length === 0) {
      return;
    }
    setRefining(true);
    try {
      const resp = await fetch('/api/courseware/refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: backendSessionId,
          version_id: backendVersionId || undefined,
          feedback: refineFeedback,
          target_types: refineTargetTypes,
        }),
      });
      if (!resp.ok) {
        toast.error(t('export.refineFailed'));
        return;
      }
      const data = await resp.json();
      applyRollbackResult(data);
      toast.success(t('export.refineSuccess'));
      setRefineOpen(false);
      setRefineFeedback('');
    } catch {
      toast.error(t('export.refineFailed'));
    } finally {
      setRefining(false);
    }
  }, [applyRollbackResult, backendSessionId, refineFeedback, refineTargetTypes, t]);

  return (
    <>
      <header className="h-20 px-8 flex items-center justify-between gap-4 bg-transparent">
        <div className="min-w-0 flex items-center gap-3">
          <button
            onClick={() => router.push('/')}
            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-300"
            title={t('generation.backToHome')}
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className="mb-0.5 text-[10px] font-bold uppercase tracking-[0.22em] text-gray-400 dark:text-gray-500">
              {t('stage.currentScene')}
            </div>
            <h1 className="truncate text-xl font-bold tracking-tight text-gray-800 dark:text-gray-200">
              {currentSceneTitle || t('common.loading')}
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-full border border-gray-100/50 bg-white/60 px-2 py-1.5 shadow-sm backdrop-blur-md dark:border-gray-700/50 dark:bg-gray-800/60">
            <div className="relative" ref={languageRef}>
              <button
                onClick={() => {
                  setLanguageOpen((prev) => !prev);
                  setThemeOpen(false);
                }}
                className="rounded-full px-3 py-1.5 text-xs font-bold text-gray-500 transition-all hover:bg-white hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
              >
                {locale === 'zh-CN' ? 'CN' : 'EN'}
              </button>
              {languageOpen && (
                <div className="absolute right-0 top-full z-50 mt-2 min-w-[120px] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
                  <button
                    onClick={() => {
                      setLocale('zh-CN');
                      setLanguageOpen(false);
                    }}
                    className={cn(
                      'block w-full px-4 py-2 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700',
                      locale === 'zh-CN' &&
                        'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400',
                    )}
                  >
                    简体中文
                  </button>
                  <button
                    onClick={() => {
                      setLocale('en-US');
                      setLanguageOpen(false);
                    }}
                    className={cn(
                      'block w-full px-4 py-2 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700',
                      locale === 'en-US' &&
                        'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400',
                    )}
                  >
                    English
                  </button>
                </div>
              )}
            </div>

            <div className="h-4 w-px bg-gray-200 dark:bg-gray-700" />

            <div className="relative" ref={themeRef}>
              <button
                onClick={() => {
                  setThemeOpen((prev) => !prev);
                  setLanguageOpen(false);
                }}
                className="rounded-full p-2 text-gray-400 transition-all hover:bg-white hover:text-gray-800 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200"
              >
                {theme === 'light' && <Sun className="h-4 w-4" />}
                {theme === 'dark' && <Moon className="h-4 w-4" />}
                {theme === 'system' && <Monitor className="h-4 w-4" />}
              </button>
              {themeOpen && (
                <div className="absolute right-0 top-full z-50 mt-2 min-w-[140px] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
                  {[
                    { id: 'light' as const, label: t('settings.themeOptions.light'), icon: Sun },
                    { id: 'dark' as const, label: t('settings.themeOptions.dark'), icon: Moon },
                    { id: 'system' as const, label: t('settings.themeOptions.system'), icon: Monitor },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        onClick={() => {
                          setTheme(item.id);
                          setThemeOpen(false);
                        }}
                        className={cn(
                          'flex w-full items-center gap-2 px-4 py-2 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700',
                          theme === item.id &&
                            'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400',
                        )}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="h-4 w-px bg-gray-200 dark:bg-gray-700" />

            <div className="relative">
              <button
                onClick={() => setSettingsOpen(true)}
                className={cn(
                  'rounded-full p-2 text-gray-400 transition-all hover:bg-white hover:text-gray-800 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200',
                  needsSetup && 'animate-setup-glow',
                )}
              >
                <Settings className="h-4 w-4" />
              </button>
              {needsSetup && (
                <span className="absolute -right-0.5 -top-0.5 flex h-3 w-3 rounded-full bg-violet-500" />
              )}
            </div>
          </div>

          <button
            onClick={() => {
              if (!backendSessionId) {
                toast.error(t('export.backendSessionMissing'));
                return;
              }
              setRefineTargetTypes(defaultRefineTargetTypes);
              setRefineOpen(true);
            }}
            disabled={!backendSessionId}
            title={t('export.refineMenuLabel')}
            className={cn(
              'flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors',
              backendSessionId
                ? 'border-emerald-200/70 text-emerald-700 hover:bg-emerald-50/70 dark:border-emerald-800/50 dark:text-emerald-300 dark:hover:bg-emerald-900/20'
                : 'cursor-not-allowed border-gray-200 text-gray-400 dark:border-gray-700 dark:text-gray-600',
            )}
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            <span>{t('export.refineMenuLabel')}</span>
          </button>

          <div className="relative" ref={exportRef}>
            <button
              onClick={() => {
                if (canExport && !isExporting) {
                  setExportMenuOpen((prev) => !prev);
                }
              }}
              disabled={!canExport || isExporting}
              className={cn(
                'rounded-full p-2 transition-all',
                canExport && !isExporting
                  ? 'text-gray-400 hover:bg-white hover:text-gray-800 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200'
                  : 'cursor-not-allowed text-gray-300 opacity-50 dark:text-gray-600',
              )}
              title={canExport ? t('export.pptx') : t('share.notReady')}
            >
              {isExporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
            </button>
            {exportMenuOpen && (
              <div className="absolute right-0 top-full z-50 mt-2 min-w-[220px] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
                <button
                  onClick={() => {
                    setExportMenuOpen(false);
                    if (canLocalExport) {
                      exportPPTX();
                    }
                  }}
                  disabled={!canLocalExport}
                  className={cn(
                    'flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors',
                    canLocalExport
                      ? 'hover:bg-gray-100 dark:hover:bg-gray-700'
                      : 'cursor-not-allowed opacity-40',
                  )}
                >
                  <FileDown className="h-4 w-4 shrink-0 text-gray-400" />
                  <span>{t('export.pptx')}</span>
                </button>

                {backendSessionId && (
                  <button
                    onClick={() => {
                      setExportMenuOpen(false);
                      window.open(
                        buildArtifactDownloadUrl(
                          backendSessionId,
                          'docx',
                          backendVersionId || undefined,
                        ),
                        '_blank',
                      );
                    }}
                    className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                  >
                    <FileDown className="h-4 w-4 shrink-0 text-gray-400" />
                    <span>{t('export.docx')}</span>
                  </button>
                )}

                <button
                  onClick={() => {
                    setExportMenuOpen(false);
                    if (canLocalExport) {
                      exportResourcePack();
                    }
                  }}
                  disabled={!canLocalExport}
                  className={cn(
                    'flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors',
                    canLocalExport
                      ? 'hover:bg-gray-100 dark:hover:bg-gray-700'
                      : 'cursor-not-allowed opacity-40',
                  )}
                >
                  <Package className="h-4 w-4 shrink-0 text-gray-400" />
                  <div>
                    <div>{t('export.resourcePack')}</div>
                    <div className="text-[11px] text-gray-400 dark:text-gray-500">
                      {t('export.resourcePackDesc')}
                    </div>
                  </div>
                </button>

                <div className="my-1 border-t border-gray-100 dark:border-gray-700" />

                <button
                  onClick={() => {
                    setExportMenuOpen(false);
                    if (!backendSessionId) {
                      toast.error(t('export.backendSessionMissing'));
                      return;
                    }
                    window.open(
                      buildVersionedUrl(
                        `/api/artifacts/export-gif?session_id=${encodeURIComponent(backendSessionId)}`,
                        backendVersionId || undefined,
                      ),
                      '_blank',
                    );
                  }}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  <Film className="h-4 w-4 shrink-0 text-gray-400" />
                  <div>
                    <div>{t('export.gifAnimation')}</div>
                    <div className="text-[11px] text-gray-400 dark:text-gray-500">
                      {t('export.gifAnimationDesc')}
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => {
                    setExportMenuOpen(false);
                    if (!backendSessionId) {
                      toast.error(t('export.backendSessionMissing'));
                      return;
                    }
                    window.open(
                      buildVersionedUrl(
                        `/api/artifacts/bundle?session_id=${encodeURIComponent(backendSessionId)}`,
                        backendVersionId || undefined,
                      ),
                      '_blank',
                    );
                  }}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  <Archive className="h-4 w-4 shrink-0 text-gray-400" />
                  <div>
                    <div>{t('export.fullBundle')}</div>
                    <div className="text-[11px] text-gray-400 dark:text-gray-500">
                      {t('export.fullBundleDesc')}
                    </div>
                  </div>
                </button>
              </div>
            )}
          </div>

          <button
            onClick={openVersionHistory}
            disabled={!backendSessionId}
            title={t('export.versionHistory')}
            className={cn(
              'rounded-full p-2 transition-all',
              backendSessionId
                ? 'text-gray-400 hover:bg-white hover:text-gray-800 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200'
                : 'cursor-not-allowed text-gray-300 opacity-50 dark:text-gray-600',
            )}
          >
            <History className="h-4 w-4" />
          </button>
        </div>
      </header>

      {(displayArtifacts.length > 0 || missingArtifactTypes.length > 0 || backendErrors.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 px-8 pb-3">
          {displayArtifacts.map((artifact) => (
            <button
              key={artifact.artifact_id}
              onClick={() => openArtifact(artifact.type)}
              title={`${getArtifactDisplayLabel(artifact.type)} 已生成`}
              className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200/70 bg-emerald-50/80 px-3 py-1 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100 dark:border-emerald-800/60 dark:bg-emerald-900/20 dark:text-emerald-300"
            >
              <span>{getArtifactDisplayLabel(artifact.type)}</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </button>
          ))}
          {missingArtifactTypes.map((type) => (
            <span
              key={`missing-${type}`}
              className="inline-flex items-center gap-1.5 rounded-full border border-red-200/70 bg-red-50/80 px-3 py-1 text-xs font-medium text-red-600 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300"
            >
              <span>{getArtifactDisplayLabel(type)}</span>
              <span>未生成</span>
            </span>
          ))}
          {backendErrors.slice(0, 2).map((error, index) => (
            <span
              key={`backend-error-${index}`}
              title={error}
              className="max-w-full truncate rounded-full border border-amber-200/70 bg-amber-50/80 px-3 py-1 text-xs text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300"
            >
              {error}
            </span>
          ))}
        </div>
      )}

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        initialSection={settingsSection}
      />

      {versionHistoryOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setVersionHistoryOpen(false)}
        >
          <div
            className="w-[480px] max-h-[70vh] overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-900"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 dark:border-gray-800">
              <div className="flex items-center gap-2">
                <History className="h-5 w-5 text-emerald-500" />
                <h2 className="font-semibold">{t('export.versionHistoryTitle')}</h2>
              </div>
              <button
                onClick={() => setVersionHistoryOpen(false)}
                className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <Settings className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[50vh] overflow-y-auto p-5">
              {versions.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  {t('export.noVersions')}
                </p>
              ) : (
                <div className="space-y-3">
                  {versions.map((version, index) => {
                    const isLatest = index === 0;
                    return (
                      <div
                        key={version.version_id}
                        className="flex items-center justify-between rounded-lg border border-gray-100 p-3 dark:border-gray-800"
                      >
                        <div className="min-w-0">
                          <div className="text-sm font-medium">
                            {t('export.versionLabel')} {versions.length - index}
                            {isLatest ? (
                              <span className="ml-2 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300">
                                Current
                              </span>
                            ) : null}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {version.created_at || version.version_id}
                          </div>
                          {(version.description || version.version_note) && (
                            <div className="mt-0.5 truncate text-xs text-muted-foreground">
                              {version.description || version.version_note}
                            </div>
                          )}
                        </div>
                        <button
                          onClick={() => rollbackVersion(version.version_id)}
                          className="rounded-lg px-3 py-1 text-xs font-medium text-emerald-600 transition-colors hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
                        >
                          {t('export.rollback')}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {refineOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setRefineOpen(false)}
        >
          <div
            className="w-[520px] overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-900"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-2 border-b border-gray-100 px-5 py-4 dark:border-gray-800">
              <MessageSquarePlus className="h-5 w-5 text-emerald-500" />
              <h2 className="font-semibold">{t('export.refineTitle')}</h2>
            </div>
            <div className="space-y-4 p-5">
              <p className="text-sm text-muted-foreground">{t('export.refineDesc')}</p>

              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">优化目标</div>
                <div className="flex gap-2">
                  {[
                    { type: 'pptx' as const, label: 'PPT' },
                    { type: 'docx' as const, label: 'Word' },
                    { type: 'game_html' as const, label: 'Game' },
                    { type: 'animation_html' as const, label: 'Animation' },
                  ].map((item) => {
                    const active = refineTargetTypes.includes(item.type);
                    return (
                      <button
                        key={item.type}
                        type="button"
                        onClick={() => {
                          setRefineTargetTypes((prev) => {
                            if (prev.includes(item.type)) {
                              return prev.length > 1
                                ? prev.filter((value) => value !== item.type)
                                : prev;
                            }
                            return [...prev, item.type];
                          });
                        }}
                        className={cn(
                          'rounded-full border px-2.5 py-1 text-xs transition-colors',
                          active
                            ? 'border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                            : 'border-gray-200 text-muted-foreground hover:bg-gray-100 dark:border-gray-700 dark:hover:bg-gray-800',
                        )}
                      >
                        {item.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <textarea
                value={refineFeedback}
                onChange={(event) => setRefineFeedback(event.target.value)}
                placeholder={t('export.refinePlaceholder')}
                className="h-28 w-full resize-none rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
              />

              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setRefineOpen(false)}
                  className="rounded-lg px-4 py-2 text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  {t('common.cancel')}
                </button>
                <button
                  disabled={refining || !refineFeedback.trim() || refineTargetTypes.length === 0}
                  onClick={submitRefine}
                  className={cn(
                    'rounded-lg px-4 py-2 text-sm font-medium transition-all',
                    refining || !refineFeedback.trim() || refineTargetTypes.length === 0
                      ? 'cursor-not-allowed bg-gray-200 text-gray-400 dark:bg-gray-700'
                      : 'bg-emerald-600 text-white shadow-sm hover:bg-emerald-700',
                  )}
                >
                  {refining ? t('export.refining') : t('export.refineSubmit')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
