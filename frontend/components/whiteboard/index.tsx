'use client';

import { useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Eraser, Hand, History, Minimize2, PencilLine, Undo2 } from 'lucide-react';
import { WhiteboardCanvas, type WhiteboardInteractionMode } from './whiteboard-canvas';
import { WhiteboardHistory } from './whiteboard-history';
import { useStageStore } from '@/lib/store';
import { useCanvasStore } from '@/lib/store/canvas';
import { useWhiteboardHistoryStore } from '@/lib/store/whiteboard-history';
import { createStageAPI } from '@/lib/api/stage-api';
import { toast } from 'sonner';
import { useI18n } from '@/lib/hooks/use-i18n';

interface WhiteboardProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
}

const STROKE_WIDTH_OPTIONS = [2, 3, 5] as const;
const STROKE_COLOR = '#111827';

/**
 * Whiteboard component
 */
export function Whiteboard({ isOpen, onClose }: WhiteboardProps) {
  const { t } = useI18n();
  const stage = useStageStore.use.stage();
  const isClearing = useCanvasStore.use.whiteboardClearing();
  const clearingRef = useRef(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [interactionMode, setInteractionMode] = useState<WhiteboardInteractionMode>('draw');
  const [strokeWidth, setStrokeWidth] = useState<number>(3);
  const snapshotCount = useWhiteboardHistoryStore((s) => s.snapshots.length);

  // Get element count for indicator
  const whiteboard = stage?.whiteboard?.at(-1);
  const elementCount = whiteboard?.elements?.length || 0;

  const stageAPI = createStageAPI(useStageStore);

  const handleClear = async () => {
    if (!whiteboard || elementCount === 0 || clearingRef.current) return;
    clearingRef.current = true;

    // Save snapshot before clearing
    if (whiteboard.elements && whiteboard.elements.length > 0) {
      useWhiteboardHistoryStore
        .getState()
        .pushSnapshot(whiteboard.elements, t('whiteboard.beforeClear'));
    }

    // Trigger cascade exit animation
    useCanvasStore.getState().setWhiteboardClearing(true);

    // Wait for cascade: base 380ms + 55ms per element, capped at 1400ms
    const animMs = Math.min(380 + elementCount * 55, 1400);
    await new Promise((resolve) => setTimeout(resolve, animMs));

    // Actually remove elements
    const result = stageAPI.whiteboard.delete(whiteboard.id);
    useCanvasStore.getState().setWhiteboardClearing(false);
    clearingRef.current = false;

    if (result.success) {
      toast.success(t('whiteboard.clearSuccess'));
    } else {
      toast.error(t('whiteboard.clearError') + result.error);
    }
  };

  const handleUndoStroke = () => {
    if (!whiteboard || elementCount === 0 || clearingRef.current) return;

    const elements = whiteboard.elements ?? [];
    const lastLine = [...elements].reverse().find((el) => el.type === 'line');
    if (!lastLine) {
      return;
    }

    const nextElements =
      lastLine.groupId && lastLine.groupId.startsWith('wb-stroke-')
        ? elements.filter((el) => el.groupId !== lastLine.groupId)
        : elements.slice(0, -1);

    const result = stageAPI.whiteboard.update({ elements: nextElements }, whiteboard.id);
    if (!result.success) {
      toast.error(t('whiteboard.undoError') + (result.error || ''));
    }
  };

  return (
    <>
      {/* Main Whiteboard Overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: 30 }}
            animate={{
              opacity: 1,
              scale: 1,
              y: 0,
              transition: {
                type: 'spring',
                stiffness: 120,
                damping: 18,
                mass: 1.2,
              },
            }}
            exit={{
              opacity: 0,
              scale: 0.95,
              y: 16,
              transition: { duration: 0.5, ease: [0.4, 0, 0.2, 1] },
            }}
            className="absolute inset-4 pointer-events-auto bg-white/95 dark:bg-gray-800/95 backdrop-blur-2xl rounded-3xl shadow-[0_32px_80px_-20px_rgba(0,0,0,0.25)] border-2 border-purple-200/60 dark:border-purple-700/60 flex flex-col overflow-hidden z-[120] ring-4 ring-purple-100/40 dark:ring-purple-800/40"
          >
            {/* Header */}
            <div className="h-14 px-6 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between shrink-0 bg-white/50 dark:bg-gray-800/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-xl bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center text-purple-600 dark:text-purple-400">
                  <PencilLine className="w-4 h-4" />
                </div>
                <span className="font-bold text-gray-800 dark:text-gray-200 tracking-tight">
                  {t('whiteboard.title')}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setInteractionMode('draw')}
                  className={`p-2 rounded-lg transition-colors ${
                    interactionMode === 'draw'
                      ? 'text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/30'
                      : 'text-gray-400 dark:text-gray-500 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20'
                  }`}
                  title={t('whiteboard.drawMode')}
                >
                  <PencilLine className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setInteractionMode('pan')}
                  className={`p-2 rounded-lg transition-colors ${
                    interactionMode === 'pan'
                      ? 'text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/30'
                      : 'text-gray-400 dark:text-gray-500 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20'
                  }`}
                  title={t('whiteboard.panMode')}
                >
                  <Hand className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setInteractionMode('erase')}
                  className={`p-2 rounded-lg transition-colors ${
                    interactionMode === 'erase'
                      ? 'text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/30'
                      : 'text-gray-400 dark:text-gray-500 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20'
                  }`}
                  title={t('whiteboard.eraseMode')}
                >
                  <Eraser className="w-4 h-4" />
                </button>
                <div className="flex items-center gap-1 px-1.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-800/60">
                  {STROKE_WIDTH_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setStrokeWidth(option)}
                      className={`w-7 h-7 rounded-md flex items-center justify-center transition-colors ${
                        strokeWidth === option
                          ? 'bg-purple-100 dark:bg-purple-900/40'
                          : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                      title={`${t('whiteboard.strokeWidth')}: ${option}px`}
                    >
                      <span
                        className="rounded-full"
                        style={{
                          width: option + 2,
                          height: option + 2,
                          backgroundColor: STROKE_COLOR,
                        }}
                      />
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={handleUndoStroke}
                  disabled={isClearing || elementCount === 0}
                  className="p-2 text-gray-400 dark:text-gray-500 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors disabled:opacity-40 disabled:pointer-events-none"
                  title={t('whiteboard.undoStroke')}
                >
                  <Undo2 className="w-4 h-4" />
                </button>
                <div className="w-px h-4 bg-gray-200 dark:bg-gray-700 mx-1" />
                <motion.button
                  type="button"
                  onClick={handleClear}
                  disabled={isClearing || elementCount === 0}
                  whileTap={{ scale: 0.9 }}
                  className="p-2 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors disabled:opacity-40 disabled:pointer-events-none"
                  title={t('whiteboard.clear')}
                >
                  <motion.div
                    animate={isClearing ? { rotate: [0, -15, 15, -10, 10, 0] } : { rotate: 0 }}
                    transition={
                      isClearing ? { duration: 0.5, ease: 'easeInOut' } : { duration: 0.2 }
                    }
                  >
                    <Eraser className="w-4 h-4" />
                  </motion.div>
                </motion.button>
                <motion.button
                  type="button"
                  onClick={() => setHistoryOpen(!historyOpen)}
                  whileTap={{ scale: 0.9 }}
                  className="relative p-2 text-gray-400 dark:text-gray-500 hover:text-purple-500 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors"
                  title={t('whiteboard.history')}
                >
                  <History className="w-4 h-4" />
                  {snapshotCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-purple-500 text-white text-[10px] font-bold flex items-center justify-center">
                      {snapshotCount}
                    </span>
                  )}
                </motion.button>
                <div className="w-px h-4 bg-gray-200 dark:bg-gray-700 mx-1" />
                <button
                  type="button"
                  onClick={onClose}
                  className="p-2 text-gray-400 dark:text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  title={t('whiteboard.minimize')}
                >
                  <Minimize2 className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Whiteboard Content Area */}
            <div className="flex-1 relative bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] dark:bg-[radial-gradient(#374151_1px,transparent_1px)] [background-size:24px_24px] overflow-hidden">
              <WhiteboardCanvas
                interactionMode={interactionMode}
                strokeColor={STROKE_COLOR}
                strokeWidth={strokeWidth}
              />

              {/* History panel */}
              <WhiteboardHistory isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />

              {/* Test panel */}
              {/* <WhiteboardTestPanel /> */}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
