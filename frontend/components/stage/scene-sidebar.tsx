'use client';

import { useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  PanelLeftClose,
  PieChart,
  Cpu,
  MousePointer2,
  BookOpen,
  Globe,
  FileText,
  Gamepad2,
  Sparkles,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ThumbnailSlide } from '@/components/slide-renderer/components/ThumbnailSlide';
import { useStageStore, useCanvasStore } from '@/lib/store';
import { useI18n } from '@/lib/hooks/use-i18n';
import type {
  InteractiveContent,
  InteractiveResourceKind,
  Scene,
  SceneType,
  SlideContent,
} from '@/lib/types/stage';
import { PENDING_SCENE_ID } from '@/lib/store/stage';

interface SceneSidebarProps {
  readonly collapsed: boolean;
  readonly onCollapseChange: (collapsed: boolean) => void;
  readonly onSceneSelect?: (sceneId: string) => void;
  readonly onRetryOutline?: (outlineId: string) => Promise<void>;
}

const DEFAULT_WIDTH = 220;
const MIN_WIDTH = 170;
const MAX_WIDTH = 400;

const RESOURCE_BADGE: Record<InteractiveResourceKind, string> = {
  lesson_plan: '教案',
  game: '游戏',
  animation: '动画',
};

export function SceneSidebar({
  collapsed,
  onCollapseChange,
  onSceneSelect,
  onRetryOutline,
}: SceneSidebarProps) {
  const { t } = useI18n();
  const router = useRouter();
  const { scenes, currentSceneId, setCurrentSceneId, generatingOutlines, generationStatus } =
    useStageStore();
  const failedOutlines = useStageStore.use.failedOutlines();
  const viewportSize = useCanvasStore.use.viewportSize();
  const viewportRatio = useCanvasStore.use.viewportRatio();

  const [retryingOutlineId, setRetryingOutlineId] = useState<string | null>(null);

  const handleRetryOutline = async (outlineId: string) => {
    if (!onRetryOutline) return;
    setRetryingOutlineId(outlineId);
    try {
      await onRetryOutline(outlineId);
    } finally {
      setRetryingOutlineId(null);
    }
  };

  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH);
  const isDraggingRef = useRef(false);

  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDraggingRef.current = true;
      const startX = e.clientX;
      const startWidth = sidebarWidth;

      const handleMouseMove = (me: MouseEvent) => {
        const delta = me.clientX - startX;
        const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + delta));
        setSidebarWidth(newWidth);
      };

      const handleMouseUp = () => {
        isDraggingRef.current = false;
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [sidebarWidth],
  );

  const getSceneTypeIcon = (type: SceneType) => {
    const icons = {
      slide: BookOpen,
      quiz: PieChart,
      interactive: MousePointer2,
      pbl: Cpu,
    };
    return icons[type] || BookOpen;
  };

  const getInteractiveResourceKind = (scene: Scene): InteractiveResourceKind | null => {
    if (scene.type !== 'interactive' || scene.content.type !== 'interactive') {
      return null;
    }
    return scene.content.resourceKind || null;
  };

  const getSceneIcon = (scene: Scene) => {
    const resourceKind = getInteractiveResourceKind(scene);
    if (resourceKind === 'lesson_plan') return FileText;
    if (resourceKind === 'game') return Gamepad2;
    if (resourceKind === 'animation') return Sparkles;
    return getSceneTypeIcon(scene.type);
  };

  const renderInteractiveThumbnail = (content: InteractiveContent) => {
    if (content.resourceKind === 'lesson_plan') {
      return (
        <div className="w-full h-full bg-gradient-to-br from-sky-50 to-cyan-50 dark:from-sky-950/30 dark:to-cyan-950/20 p-2 flex flex-col">
          <div className="flex items-center gap-1.5 mb-2">
            <FileText className="w-3.5 h-3.5 text-sky-500 dark:text-sky-400" />
            <div className="h-1.5 flex-1 rounded-full bg-sky-200/70 dark:bg-sky-700/40" />
          </div>
          <div className="space-y-1.5">
            {[0, 1, 2, 3].map((line) => (
              <div
                key={line}
                className={cn(
                  'h-1 rounded-full bg-sky-200/80 dark:bg-sky-700/35',
                  line === 0 ? 'w-4/5' : line === 3 ? 'w-3/5' : 'w-full',
                )}
              />
            ))}
          </div>
          <div className="mt-auto grid grid-cols-2 gap-1.5 pt-3">
            {[0, 1].map((card) => (
              <div
                key={card}
                className="rounded-md border border-sky-200/60 bg-white/70 dark:border-sky-800/25 dark:bg-white/5 p-1.5"
              >
                <div className="h-1 w-3/4 rounded-full bg-sky-300/70 dark:bg-sky-600/40" />
                <div className="mt-1 h-0.5 w-full rounded-full bg-sky-100 dark:bg-sky-900/50" />
                <div className="mt-1 h-0.5 w-4/5 rounded-full bg-sky-100 dark:bg-sky-900/50" />
              </div>
            ))}
          </div>
        </div>
      );
    }

    if (content.resourceKind === 'game') {
      return (
        <div className="w-full h-full bg-gradient-to-br from-violet-50 to-fuchsia-50 dark:from-violet-950/30 dark:to-fuchsia-950/20 p-2 flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <Gamepad2 className="w-3.5 h-3.5 text-violet-500 dark:text-violet-400" />
            <div className="flex gap-1">
              <div className="w-2 h-2 rounded-full bg-violet-300/80 dark:bg-violet-600/50" />
              <div className="w-2 h-2 rounded-full bg-fuchsia-300/80 dark:bg-fuchsia-600/50" />
            </div>
          </div>
          <div className="flex-1 rounded-xl border border-violet-200/60 bg-white/70 dark:border-violet-800/25 dark:bg-white/5 px-3 py-2">
            <div className="grid grid-cols-3 gap-1.5">
              {[0, 1, 2, 3, 4, 5].map((cell) => (
                <div
                  key={cell}
                  className={cn(
                    'aspect-square rounded-md',
                    cell % 2 === 0
                      ? 'bg-violet-200/70 dark:bg-violet-700/35'
                      : 'bg-fuchsia-200/70 dark:bg-fuchsia-700/35',
                  )}
                />
              ))}
            </div>
          </div>
        </div>
      );
    }

    if (content.resourceKind === 'animation') {
      return (
        <div className="w-full h-full bg-gradient-to-br from-amber-50 to-rose-50 dark:from-amber-950/30 dark:to-rose-950/20 p-2 flex flex-col">
          <div className="flex items-center gap-1.5 mb-2">
            <Sparkles className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" />
            <div className="h-1.5 flex-1 rounded-full bg-amber-200/70 dark:bg-amber-700/40" />
          </div>
          <div className="flex-1 rounded-xl border border-amber-200/60 bg-white/70 dark:border-amber-800/25 dark:bg-white/5 p-2 flex items-end gap-1.5">
            {[28, 48, 64, 84].map((height, index) => (
              <div
                key={height}
                className={cn(
                  'flex-1 rounded-t-xl',
                  index % 2 === 0
                    ? 'bg-amber-300/80 dark:bg-amber-600/45'
                    : 'bg-rose-300/80 dark:bg-rose-600/45',
                )}
                style={{ height: `${height}%` }}
              />
            ))}
          </div>
        </div>
      );
    }

    return (
      <div className="w-full h-full bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-950/30 dark:to-teal-950/20 p-1.5 flex flex-col">
        <div className="flex items-center gap-1 mb-1 pb-1 border-b border-emerald-200/40 dark:border-emerald-700/20">
          <div className="flex gap-0.5">
            <div className="w-1 h-1 rounded-full bg-red-300 dark:bg-red-500/60" />
            <div className="w-1 h-1 rounded-full bg-amber-300 dark:bg-amber-500/60" />
            <div className="w-1 h-1 rounded-full bg-green-300 dark:bg-green-500/60" />
          </div>
          <div className="h-1.5 flex-1 bg-emerald-200/40 dark:bg-emerald-700/30 rounded-full ml-0.5" />
        </div>
        <div className="flex-1 flex gap-1">
          <div className="w-1/4 space-y-1 pt-0.5">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-0.5 w-full bg-emerald-200/60 dark:bg-emerald-700/30 rounded-full"
              />
            ))}
          </div>
          <div className="flex-1 bg-emerald-100/40 dark:bg-emerald-800/20 rounded flex items-center justify-center border border-emerald-200/40 dark:border-emerald-700/20">
            <Globe className="w-4 h-4 text-emerald-300/80 dark:text-emerald-600/50" />
          </div>
        </div>
      </div>
    );
  };

  const displayWidth = collapsed ? 0 : sidebarWidth;

  return (
    <div
      style={{
        width: displayWidth,
        transition: isDraggingRef.current ? 'none' : 'width 0.3s ease',
      }}
      className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border-r border-gray-100 dark:border-gray-800 shadow-[2px_0_24px_rgba(0,0,0,0.02)] flex flex-col shrink-0 z-20 relative overflow-visible"
    >
      {/* Drag handle */}
      {!collapsed && (
        <div
          onMouseDown={handleDragStart}
          className="absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize z-50 group hover:bg-emerald-400/30 dark:hover:bg-emerald-600/30 active:bg-emerald-500/40 dark:active:bg-emerald-500/40 transition-colors"
        >
          <div className="absolute right-0.5 top-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-gray-300 dark:bg-gray-600 group-hover:bg-emerald-400 dark:group-hover:bg-emerald-500 transition-colors" />
        </div>
      )}

      <div className={cn('flex flex-col w-full h-full overflow-hidden', collapsed && 'hidden')}>
        {/* Logo Header */}
        <div className="h-10 flex items-center justify-between shrink-0 relative mt-3 mb-1 px-3">
          <button
            onClick={() => router.push('/')}
            className="flex items-center gap-2 cursor-pointer rounded-lg px-1.5 -mx-1.5 py-1 -my-1 hover:bg-gray-100/80 dark:hover:bg-gray-800/60 active:scale-[0.97] transition-all duration-150"
            title={t('generation.backToHome')}
          >
            <span className="text-sm font-bold bg-gradient-to-r from-emerald-600 to-teal-500 bg-clip-text text-transparent truncate">智绘生物</span>
          </button>
          <button
            onClick={() => onCollapseChange(true)}
            className="w-7 h-7 shrink-0 rounded-lg flex items-center justify-center bg-gray-100/80 dark:bg-gray-800/80 text-gray-500 dark:text-gray-400 ring-1 ring-black/[0.04] dark:ring-white/[0.06] hover:bg-gray-200/90 dark:hover:bg-gray-700/90 hover:text-gray-700 dark:hover:text-gray-200 active:scale-90 transition-all duration-200"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        {/* Scenes List */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-2 scrollbar-hide pt-1">
          {scenes.map((scene, index) => {
            const isActive = currentSceneId === scene.id;
            const Icon = getSceneIcon(scene);
            const isSlide = scene.type === 'slide';
            const slideContent = isSlide ? (scene.content as SlideContent) : null;
            const interactiveContent =
              scene.type === 'interactive' && scene.content.type === 'interactive'
                ? scene.content
                : null;
            const resourceKind = interactiveContent?.resourceKind || null;

            return (
              <div
                key={scene.id}
                onClick={() => {
                  if (onSceneSelect) {
                    onSceneSelect(scene.id);
                  } else {
                    setCurrentSceneId(scene.id);
                  }
                }}
                className={cn(
                  'group relative rounded-lg transition-all duration-200 cursor-pointer flex flex-col gap-1 p-1.5',
                  isActive
                    ? 'bg-emerald-50 dark:bg-emerald-900/20 ring-1 ring-emerald-200 dark:ring-emerald-700'
                    : 'hover:bg-gray-50/80 dark:hover:bg-gray-800/50',
                )}
              >
                {/* Scene Header */}
                <div className="flex justify-between items-center px-2 pt-0.5">
                  <div className="flex items-center gap-2 max-w-full">
                    <span
                      className={cn(
                        'text-[10px] font-black w-4 h-4 rounded-full flex items-center justify-center shrink-0',
                        isActive
                          ? 'bg-emerald-600 dark:bg-emerald-500 text-white shadow-sm shadow-emerald-500/30'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400',
                      )}
                      >
                      {index + 1}
                    </span>
                    {!isSlide && (
                      <Icon
                        className={cn(
                          'w-3.5 h-3.5 shrink-0',
                          isActive
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-gray-400 dark:text-gray-500',
                        )}
                      />
                    )}
                    <span
                      className={cn(
                        'text-xs font-bold truncate transition-colors',
                        isActive
                          ? 'text-emerald-700 dark:text-emerald-300'
                          : 'text-gray-600 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100',
                      )}
                    >
                      {scene.title}
                    </span>
                    {resourceKind && (
                      <span
                        className={cn(
                          'shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold tracking-wide',
                          resourceKind === 'lesson_plan'
                            ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300'
                            : resourceKind === 'game'
                              ? 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300'
                              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
                        )}
                      >
                        {RESOURCE_BADGE[resourceKind]}
                      </span>
                    )}
                  </div>
                </div>

                {/* Thumbnail */}
                <div className="relative aspect-video w-full rounded overflow-hidden bg-gray-100 dark:bg-gray-800 ring-1 ring-black/5 dark:ring-white/5">
                  <div className="absolute inset-0 flex items-center justify-center">
                    {isSlide && slideContent ? (
                      <ThumbnailSlide
                        slide={slideContent.canvas}
                        viewportSize={viewportSize}
                        viewportRatio={viewportRatio}
                        size={Math.max(100, sidebarWidth - 28)}
                      />
                    ) : scene.type === 'quiz' ? (
                      /* Quiz: question bar + 2x2 option grid */
                      <div className="w-full h-full bg-gradient-to-br from-orange-50 to-amber-50 dark:from-orange-950/30 dark:to-amber-950/20 p-2 flex flex-col">
                        <div className="h-1.5 w-4/5 bg-orange-200/70 dark:bg-orange-700/30 rounded-full mb-1.5" />
                        <div className="flex-1 grid grid-cols-2 gap-1">
                          {[0, 1, 2, 3].map((i) => (
                            <div
                              key={i}
                              className={cn(
                                'rounded flex items-center gap-1 px-1',
                                i === 1
                                  ? 'bg-orange-400/20 dark:bg-orange-500/20 border border-orange-300/50 dark:border-orange-600/30'
                                  : 'bg-white/60 dark:bg-white/5 border border-orange-100/60 dark:border-orange-800/20',
                              )}
                            >
                              <div
                                className={cn(
                                  'w-1.5 h-1.5 rounded-full shrink-0',
                                  i === 1
                                    ? 'bg-orange-400 dark:bg-orange-500'
                                    : 'bg-orange-200 dark:bg-orange-700/50',
                                )}
                              />
                              <div
                                className={cn(
                                  'h-1 rounded-full flex-1',
                                  i === 1
                                    ? 'bg-orange-300/60 dark:bg-orange-600/40'
                                    : 'bg-orange-100/80 dark:bg-orange-800/30',
                                )}
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : interactiveContent ? (
                      renderInteractiveThumbnail(interactiveContent)
                    ) : scene.type === 'pbl' ? (
                      /* PBL: kanban board with 3 columns */
                      <div className="w-full h-full bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-blue-950/30 dark:to-indigo-950/20 p-1.5 flex flex-col">
                        <div className="flex items-center gap-1 mb-1.5">
                          <div className="w-1.5 h-1.5 rounded bg-blue-300 dark:bg-blue-600" />
                          <div className="h-1 w-8 bg-blue-200/60 dark:bg-blue-700/30 rounded-full" />
                        </div>
                        <div className="flex-1 flex gap-1 overflow-hidden">
                          {[0, 1, 2].map((col) => (
                            <div
                              key={col}
                              className="flex-1 bg-white/50 dark:bg-white/5 rounded p-0.5 flex flex-col gap-0.5"
                            >
                              <div
                                className={cn(
                                  'h-0.5 w-3 rounded-full mb-0.5',
                                  col === 0
                                    ? 'bg-blue-300/70'
                                    : col === 1
                                      ? 'bg-amber-300/70'
                                      : 'bg-green-300/70',
                                )}
                              />
                              {Array.from({
                                length: col === 0 ? 3 : col === 1 ? 2 : 1,
                              }).map((_, i) => (
                                <div
                                  key={i}
                                  className="h-2 w-full bg-blue-100/60 dark:bg-blue-800/20 rounded border border-blue-200/30 dark:border-blue-700/20"
                                />
                              ))}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      /* Fallback */
                      <div className="w-full h-full flex flex-col items-center justify-center gap-1 bg-gray-50 dark:bg-gray-800 text-gray-300 dark:text-gray-500">
                        <Icon className="w-4 h-4" />
                        <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">
                          {scene.type}
                        </span>
                      </div>
                    )}

                    {isSlide && (
                      <div
                        className={cn(
                          'absolute inset-0 bg-emerald-500/0 transition-colors',
                          isActive
                            ? 'bg-emerald-500/0'
                            : 'group-hover:bg-black/5 dark:group-hover:bg-white/5',
                        )}
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {/* Single placeholder for the next generating page (clickable) */}
          {generatingOutlines.length > 0 &&
            (() => {
              const outline = generatingOutlines[0];
              const isFailed = failedOutlines.some((f) => f.id === outline.id);
              const isRetrying = retryingOutlineId === outline.id;
              const isPaused = generationStatus === 'paused';
              const isActive = currentSceneId === PENDING_SCENE_ID;

              return (
                <div
                  key={`generating-${outline.id}`}
                  onClick={() => {
                    if (isFailed) return;
                    if (onSceneSelect) {
                      onSceneSelect(PENDING_SCENE_ID);
                    } else {
                      setCurrentSceneId(PENDING_SCENE_ID);
                    }
                  }}
                  className={cn(
                    'group relative rounded-lg flex flex-col gap-1 p-1.5 transition-all duration-200',
                    isFailed
                      ? 'opacity-100 cursor-default'
                      : 'cursor-pointer hover:bg-gray-50/80 dark:hover:bg-gray-800/50',
                    !isFailed && !isActive && 'opacity-60',
                    isActive &&
                      !isFailed &&
                      'bg-emerald-50 dark:bg-emerald-900/20 ring-1 ring-emerald-200 dark:ring-emerald-700 opacity-100',
                  )}
                >
                  {/* Scene Header */}
                  <div className="flex justify-between items-center px-2 pt-0.5">
                    <div className="flex items-center gap-2 max-w-full">
                      <span
                        className={cn(
                          'text-[10px] font-black w-4 h-4 rounded-full flex items-center justify-center shrink-0',
                          isActive && !isFailed
                            ? 'bg-emerald-600 dark:bg-emerald-500 text-white shadow-sm shadow-emerald-500/30'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500',
                        )}
                      >
                        {scenes.length + 1}
                      </span>
                      <span
                        className={cn(
                          'text-xs font-bold truncate transition-colors',
                          isActive && !isFailed
                            ? 'text-emerald-700 dark:text-emerald-300'
                            : isFailed
                              ? 'text-gray-700 dark:text-gray-200'
                              : 'text-gray-400 dark:text-gray-500',
                        )}
                      >
                        {outline.title}
                      </span>
                    </div>
                  </div>

                  {/* Skeleton Thumbnail */}
                  <div
                    className={cn(
                      'relative aspect-video w-full rounded overflow-hidden ring-1',
                      isFailed
                        ? 'bg-red-50/30 dark:bg-red-950/10 ring-red-100 dark:ring-red-900/20'
                        : 'bg-gray-100 dark:bg-gray-800 ring-black/5 dark:ring-white/5',
                    )}
                  >
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5">
                      {isFailed ? (
                        <div className="flex items-center gap-1 text-xs font-medium text-red-500/90 dark:text-red-400">
                          {onRetryOutline ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRetryOutline(outline.id);
                              }}
                              disabled={isRetrying}
                              className="p-1 -ml-1 rounded-md hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors active:scale-95 disabled:opacity-50 disabled:active:scale-100"
                              title={t('generation.retryScene')}
                            >
                              <RefreshCw
                                className={cn('w-3.5 h-3.5', isRetrying && 'animate-spin')}
                              />
                            </button>
                          ) : (
                            <AlertCircle className="w-3.5 h-3.5" />
                          )}
                          <span>
                            {isRetrying
                              ? t('generation.retryingScene')
                              : t('stage.generationFailed')}
                          </span>
                        </div>
                      ) : (
                        <>
                          <div
                            className={cn(
                              'h-2 w-3/5 bg-gray-200 dark:bg-gray-700 rounded',
                              !isPaused && 'animate-pulse',
                            )}
                          />
                          <div
                            className={cn(
                              'h-1.5 w-2/5 bg-gray-200 dark:bg-gray-700 rounded',
                              !isPaused && 'animate-pulse',
                            )}
                          />
                          <span className="text-[9px] font-medium text-gray-400 dark:text-gray-500 mt-0.5">
                            {isPaused ? t('stage.paused') : t('stage.generating')}
                          </span>
                        </>
                      )}
                    </div>
                    {!isFailed && !isPaused && (
                      <div className="absolute inset-0 -translate-x-full animate-[shimmer_2s_infinite] bg-gradient-to-r from-transparent via-white/40 dark:via-white/10 to-transparent" />
                    )}
                  </div>
                </div>
              );
            })()}
        </div>

        {/* Spacer to push toggle button area */}
        <div className="mt-auto" />
      </div>
    </div>
  );
}
