'use client';

import { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useStageStore } from '@/lib/store';
import { useCanvasStore } from '@/lib/store/canvas';
import { useWhiteboardHistoryStore } from '@/lib/store/whiteboard-history';
import { createStageAPI } from '@/lib/api/stage-api';
import { ScreenElement } from '@/components/slide-renderer/Editor/ScreenElement';
import { elementFingerprint } from '@/lib/utils/element-fingerprint';
import type { PPTElement, PPTLineElement } from '@/lib/types/slides';
import { useI18n } from '@/lib/hooks/use-i18n';
import { getElementRange } from '@/lib/utils/element';

type ElementBounds = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

export type WhiteboardInteractionMode = 'draw' | 'pan' | 'erase';

type InteractiveWhiteboardCanvasProps = {
  autoFitTransform: {
    scale: number;
    tx: number;
    ty: number;
  };
  canvasHeight: number;
  canvasWidth: number;
  containerScale: number;
  elements: PPTElement[];
  interactionMode: WhiteboardInteractionMode;
  isClearing: boolean;
  onEraseAtPoint: (point: [number, number]) => void;
  onStrokeCreate: (points: Array<[number, number]>) => void;
  readyHintText: string;
  readyText: string;
  resetViewText: string;
  strokeColor: string;
  strokeWidth: number;
  zoomHintText: string;
};

const MIN_DRAW_POINT_DISTANCE = 1.5;
const MIN_STROKE_SEGMENT_LENGTH = 0.8;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function buildStrokeLineElements(
  points: Array<[number, number]>,
  strokeWidth: number,
  strokeColor: string,
  groupId: string,
): PPTLineElement[] {
  const segments: PPTLineElement[] = [];

  for (let i = 1; i < points.length; i += 1) {
    const [sx, sy] = points[i - 1];
    const [ex, ey] = points[i];
    if (Math.hypot(ex - sx, ey - sy) < MIN_STROKE_SEGMENT_LENGTH) {
      continue;
    }

    const left = Math.min(sx, ex);
    const top = Math.min(sy, ey);
    const start: [number, number] = [sx - left, sy - top];
    const end: [number, number] = [ex - left, ey - top];

    segments.push({
      id: `line_${groupId}_${i}`,
      type: 'line',
      left,
      top,
      width: strokeWidth,
      start,
      end,
      style: 'solid',
      color: strokeColor,
      points: ['', ''],
      groupId,
    });
  }

  return segments;
}

function distancePointToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;

  if (lenSq === 0) {
    return Math.hypot(px - x1, py - y1);
  }

  const t = clamp(((px - x1) * dx + (py - y1) * dy) / lenSq, 0, 1);
  const projX = x1 + t * dx;
  const projY = y1 + t * dy;
  return Math.hypot(px - projX, py - projY);
}

function hitTestLineElement(element: PPTLineElement, point: [number, number], tolerance = 10): boolean {
  const x1 = element.left + element.start[0];
  const y1 = element.top + element.start[1];
  const x2 = element.left + element.end[0];
  const y2 = element.top + element.end[1];
  const threshold = Math.max(tolerance, (element.width ?? 2) * 2.5);

  const minX = Math.min(x1, x2) - threshold;
  const maxX = Math.max(x1, x2) + threshold;
  const minY = Math.min(y1, y2) - threshold;
  const maxY = Math.max(y1, y2) + threshold;
  if (point[0] < minX || point[0] > maxX || point[1] < minY || point[1] > maxY) {
    return false;
  }

  const distance = distancePointToSegment(point[0], point[1], x1, y1, x2, y2);
  return distance <= threshold;
}

function getLineBounds(element: PPTLineElement): ElementBounds {
  const originX = element.left ?? 0;
  const originY = element.top ?? 0;
  const points: Array<[number, number]> = [element.start, element.end];

  if (element.broken) {
    points.push(element.broken);
  }

  if (element.broken2) {
    const horizontalFirst =
      Math.abs(element.end[0] - element.start[0]) >= Math.abs(element.end[1] - element.start[1]);

    if (horizontalFirst) {
      points.push([element.broken2[0], element.start[1]], [element.broken2[0], element.end[1]]);
    } else {
      points.push([element.start[0], element.broken2[1]], [element.end[0], element.broken2[1]]);
    }
  }

  if (element.curve) {
    points.push(element.curve);
  }

  if (element.cubic) {
    points.push(...element.cubic);
  }

  const xs = points.map(([x]) => originX + x);
  const ys = points.map(([, y]) => originY + y);
  const strokePad = Math.max(element.width ?? 0, 1) / 2;
  const markerPad = element.points.some(Boolean) ? Math.max(element.width ?? 0, 1) * 1.5 : 0;
  const pad = strokePad + markerPad;

  return {
    minX: Math.min(...xs) - pad,
    minY: Math.min(...ys) - pad,
    maxX: Math.max(...xs) + pad,
    maxY: Math.max(...ys) + pad,
  };
}

function getWhiteboardElementBounds(element: PPTElement): ElementBounds {
  if (element.type === 'line') {
    return getLineBounds(element);
  }

  return getElementRange(element);
}

function AnimatedElement({
  element,
  index,
  isClearing,
  totalElements,
}: {
  element: PPTElement;
  index: number;
  isClearing: boolean;
  totalElements: number;
}) {
  const clearDelay = isClearing ? (totalElements - 1 - index) * 0.055 : 0;
  const clearRotate = isClearing ? (index % 2 === 0 ? 1 : -1) * (2 + index * 0.4) : 0;

  return (
    <motion.div
      layout={false}
      initial={false}
      animate={
        isClearing
          ? {
              opacity: 0,
              scale: 0.35,
              y: -35,
              rotate: clearRotate,
              filter: 'blur(8px)',
              transition: {
                duration: 0.38,
                delay: clearDelay,
                ease: [0.5, 0, 1, 0.6],
              },
            }
          : {
              opacity: 1,
              scale: 1,
              y: 0,
              rotate: 0,
              filter: 'blur(0px)',
              transition: {
                duration: 0.12,
                ease: [0.16, 1, 0.3, 1],
              },
            }
      }
      exit={{
        opacity: 0,
        scale: 0.85,
        transition: { duration: 0.2 },
      }}
      className="absolute inset-0"
      style={{ pointerEvents: isClearing ? 'none' : undefined }}
    >
      <div style={{ pointerEvents: 'auto' }}>
        <ScreenElement elementInfo={element} elementIndex={index} animate />
      </div>
    </motion.div>
  );
}

function InteractiveWhiteboardCanvas({
  autoFitTransform,
  canvasHeight,
  canvasWidth,
  containerScale,
  elements,
  interactionMode,
  isClearing,
  onEraseAtPoint,
  onStrokeCreate,
  readyHintText,
  readyText,
  resetViewText,
  strokeColor,
  strokeWidth,
  zoomHintText,
}: InteractiveWhiteboardCanvasProps) {
  const [viewZoom, setViewZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isDrawing, setIsDrawing] = useState(false);
  const [isErasing, setIsErasing] = useState(false);
  const [isPanning, setIsPanning] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [hintTimedOut, setHintTimedOut] = useState(false);
  const [drawingPoints, setDrawingPoints] = useState<Array<[number, number]>>([]);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const drawingPointsRef = useRef<Array<[number, number]>>([]);
  const prevElementsLengthRef = useRef(elements.length);
  const resetTimerRef = useRef<number | null>(null);
  const hintTimerRef = useRef<number | null>(null);
  const hintEpochRef = useRef(0);
  const canvasRef = useRef<HTMLDivElement>(null);

  const isViewModified = viewZoom !== 1 || panX !== 0 || panY !== 0;
  const hasOverflow = autoFitTransform.scale < 1;
  const canPan = elements.length > 0 && (hasOverflow || isViewModified);
  const hintEpoch = elements.length > 0 && !isViewModified ? 1 : 0;
  const showHint = hintEpoch === 1 && !hintTimedOut;

  const resolveContentPoint = useCallback(
    (clientX: number, clientY: number): [number, number] | null => {
      const canvas = canvasRef.current;
      if (!canvas) {
        return null;
      }

      const rect = canvas.getBoundingClientRect();
      const localX = (clientX - rect.left) / Math.max(containerScale, 0.001);
      const localY = (clientY - rect.top) / Math.max(containerScale, 0.001);
      const contentScale = Math.max(autoFitTransform.scale * viewZoom, 0.001);
      const tx = autoFitTransform.tx + panX;
      const ty = autoFitTransform.ty + panY;
      const x = (localX - tx) / contentScale;
      const y = (localY - ty) / contentScale;

      return [clamp(x, 0, canvasWidth), clamp(y, 0, canvasHeight)];
    },
    [autoFitTransform.scale, autoFitTransform.tx, autoFitTransform.ty, canvasHeight, canvasWidth, containerScale, panX, panY, viewZoom],
  );

  const eraseAtClientPoint = useCallback(
    (clientX: number, clientY: number) => {
      const point = resolveContentPoint(clientX, clientY);
      if (!point) {
        return;
      }
      onEraseAtPoint(point);
    },
    [onEraseAtPoint, resolveContentPoint],
  );

  useEffect(() => {
    if (hintEpoch === 0) {
      return;
    }

    const epoch = ++hintEpochRef.current;
    hintTimerRef.current = window.setTimeout(() => {
      if (hintEpochRef.current === epoch) {
        setHintTimedOut(true);
      }
    }, 3000);

    return () => {
      if (hintTimerRef.current !== null) {
        window.clearTimeout(hintTimerRef.current);
        hintTimerRef.current = null;
      }
    };
  }, [hintEpoch]);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0 || isClearing) {
        return;
      }

      if (interactionMode === 'draw') {
        e.preventDefault();
        const point = resolveContentPoint(e.clientX, e.clientY);
        if (!point) {
          return;
        }

        setIsPanning(false);
        setIsErasing(false);
        setIsDrawing(true);
        setHintTimedOut(true);
        drawingPointsRef.current = [point];
        setDrawingPoints([point]);
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }

      if (interactionMode === 'erase') {
        e.preventDefault();
        setIsPanning(false);
        setIsDrawing(false);
        setHintTimedOut(true);
        drawingPointsRef.current = [];
        setDrawingPoints([]);
        setIsErasing(true);
        eraseAtClientPoint(e.clientX, e.clientY);
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }

      if (!canPan) {
        return;
      }

      e.preventDefault();
      setIsErasing(false);
      setIsPanning(true);
      setHintTimedOut(false);
      panStartRef.current = { x: e.clientX, y: e.clientY, panX, panY };
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    },
    [canPan, eraseAtClientPoint, interactionMode, isClearing, panX, panY, resolveContentPoint],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (interactionMode === 'draw') {
        if (!isDrawing) {
          return;
        }

        const point = resolveContentPoint(e.clientX, e.clientY);
        if (!point) {
          return;
        }

        const prev = drawingPointsRef.current.at(-1);
        if (prev && Math.hypot(point[0] - prev[0], point[1] - prev[1]) < MIN_DRAW_POINT_DISTANCE) {
          return;
        }

        drawingPointsRef.current = [...drawingPointsRef.current, point];
        setDrawingPoints(drawingPointsRef.current);
        return;
      }

      if (interactionMode === 'erase') {
        if (!isErasing) {
          return;
        }

        eraseAtClientPoint(e.clientX, e.clientY);
        return;
      }

      if (!isPanning) {
        return;
      }

      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      const effectiveScale = Math.max(containerScale, 0.001);

      setPanX(panStartRef.current.panX + dx / effectiveScale);
      setPanY(panStartRef.current.panY + dy / effectiveScale);
    },
    [containerScale, eraseAtClientPoint, interactionMode, isDrawing, isErasing, isPanning, resolveContentPoint],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      const target = e.currentTarget as HTMLElement;
      if (target.hasPointerCapture(e.pointerId)) {
        target.releasePointerCapture(e.pointerId);
      }

      if (interactionMode === 'draw') {
        if (!isDrawing) {
          return;
        }

        setIsDrawing(false);
        const points = drawingPointsRef.current;

        if (points.length > 1) {
          onStrokeCreate(points);
        }
        drawingPointsRef.current = [];
        setDrawingPoints([]);
        return;
      }

      if (interactionMode === 'erase') {
        setIsErasing(false);
        return;
      }

      setIsPanning(false);
    },
    [interactionMode, isDrawing, onStrokeCreate],
  );

  const resetView = useCallback((animate: boolean) => {
    setIsPanning(false);
    setIsDrawing(false);
    setIsErasing(false);
    drawingPointsRef.current = [];
    setDrawingPoints([]);
    setIsResetting(animate);
    setHintTimedOut(false);
    setViewZoom(1);
    setPanX(0);
    setPanY(0);

    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }

    if (!animate) {
      return;
    }

    resetTimerRef.current = window.setTimeout(() => {
      setIsResetting(false);
      resetTimerRef.current = null;
    }, 250);
  }, []);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) {
      return;
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (interactionMode !== 'pan' || elements.length === 0) {
        return;
      }

      setHintTimedOut(false);
      const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
      setViewZoom((prev) => Math.min(5, Math.max(0.2, prev * zoomFactor)));
    };

    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [elements.length, interactionMode]);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const prevLength = prevElementsLengthRef.current;
    const nextLength = elements.length;
    prevElementsLengthRef.current = nextLength;

    const clearedBoard = prevLength > 0 && nextLength === 0;
    const firstContentLoaded = prevLength === 0 && nextLength > 0;
    if (!clearedBoard && !firstContentLoaded) {
      return;
    }

    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) {
        resetView(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [elements.length, resetView]);

  const handleDoubleClick = useCallback(
    (e?: React.MouseEvent) => {
      if (interactionMode !== 'pan') {
        return;
      }

      e?.preventDefault();
      resetView(true);
    },
    [interactionMode, resetView],
  );

  const contentTransform = useMemo(() => {
    const scale = autoFitTransform.scale * viewZoom;
    const tx = autoFitTransform.tx + panX;
    const ty = autoFitTransform.ty + panY;
    return `translate(${tx}px, ${ty}px) scale(${scale})`;
  }, [autoFitTransform, panX, panY, viewZoom]);

  return (
    <div
      ref={canvasRef}
      className="relative bg-white shadow-2xl rounded-lg overflow-hidden select-none"
      style={{
        width: canvasWidth,
        height: canvasHeight,
        transform: `scale(${containerScale})`,
        transformOrigin: 'top left',
        cursor:
          isDrawing || interactionMode === 'draw'
            ? 'crosshair'
            : isErasing || interactionMode === 'erase'
              ? 'cell'
            : isPanning
              ? 'grabbing'
              : canPan
                ? 'grab'
                : undefined,
        touchAction: 'none',
      }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={handleDoubleClick}
    >
      <AnimatePresence>
        {elements.length === 0 && !isClearing && (
          <motion.div
            key="placeholder"
            initial={{ opacity: 0 }}
            animate={{
              opacity: 1,
              transition: { delay: 0.25, duration: 0.4 },
            }}
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
            className="absolute inset-0 flex items-center justify-center"
          >
            <div className="text-center text-gray-400">
              <p className="text-lg font-medium">{readyText}</p>
              <p className="text-sm mt-1">{readyHintText}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div
        className="absolute inset-0"
        style={{
          transform: contentTransform,
          transformOrigin: '0 0',
          transition: isResetting ? 'transform 0.25s ease-out' : undefined,
        }}
      >
        <AnimatePresence mode="popLayout">
          {elements.map((element, index) => (
            <AnimatedElement
              key={element.id}
              element={element}
              index={index}
              isClearing={isClearing}
              totalElements={elements.length}
            />
          ))}
        </AnimatePresence>
        {drawingPoints.length > 1 && (
          <svg
            width={canvasWidth}
            height={canvasHeight}
            className="absolute inset-0 pointer-events-none overflow-visible"
          >
            <polyline
              points={drawingPoints.map(([x, y]) => `${x},${y}`).join(' ')}
              fill="none"
              stroke={strokeColor}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </div>

      <AnimatePresence>
        {interactionMode === 'pan' && showHint && !isViewModified && elements.length > 0 && (
          <motion.div
            key="zoom-hint"
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.5, transition: { delay: 0.6, duration: 0.4 } }}
            exit={{ opacity: 0, transition: { duration: 0.3 } }}
            className="absolute bottom-3 left-3 z-50 px-2.5 py-1 rounded-md
              bg-black/40 text-white text-xs backdrop-blur-sm select-none pointer-events-none"
          >
            {zoomHintText}
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {interactionMode === 'pan' && isViewModified && elements.length > 0 && (
          <motion.button
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 0.7 }}
            exit={{ opacity: 0 }}
            whileHover={{ opacity: 1 }}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              handleDoubleClick();
            }}
            className="absolute bottom-3 right-3 z-50 px-2.5 py-1 rounded-md
              bg-black/60 text-white text-xs backdrop-blur-sm
              hover:bg-black/80 transition-colors cursor-pointer select-none"
          >
            {resetViewText}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * Whiteboard canvas with pan, zoom, auto-fit, and history auto-snapshot support.
 */
export function WhiteboardCanvas({
  interactionMode = 'draw',
  strokeColor = '#111827',
  strokeWidth = 3,
}: {
  interactionMode?: WhiteboardInteractionMode;
  strokeColor?: string;
  strokeWidth?: number;
}) {
  const { t } = useI18n();
  const stage = useStageStore.use.stage();
  const isClearing = useCanvasStore.use.whiteboardClearing();
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerScale, setContainerScale] = useState(1);
  const stageAPI = useMemo(() => createStageAPI(useStageStore), []);

  const whiteboard = stage?.whiteboard?.at(-1);
  const rawElements = whiteboard?.elements;
  const elements = useMemo(() => rawElements ?? [], [rawElements]);
  const elementsKey = useMemo(() => elementFingerprint(elements), [elements]);
  const elementsRef = useRef(elements);
  const snapshotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleEraseAtPoint = useCallback(
    (point: [number, number]) => {
      const wbResult = stageAPI.whiteboard.get();
      if (!wbResult.success || !wbResult.data) {
        return;
      }

      const currentElements = wbResult.data.elements ?? [];
      if (currentElements.length === 0) {
        return;
      }

      let hitIndex = -1;
      let hitLine: PPTLineElement | null = null;
      for (let i = currentElements.length - 1; i >= 0; i -= 1) {
        const element = currentElements[i];
        if (element.type !== 'line') {
          continue;
        }
        if (hitTestLineElement(element, point)) {
          hitIndex = i;
          hitLine = element;
          break;
        }
      }

      if (!hitLine || hitIndex < 0) {
        return;
      }

      const nextElements =
        hitLine.groupId && hitLine.groupId.startsWith('wb-stroke-')
          ? currentElements.filter((el) => el.groupId !== hitLine.groupId)
          : [...currentElements.slice(0, hitIndex), ...currentElements.slice(hitIndex + 1)];

      if (nextElements.length === currentElements.length) {
        return;
      }

      const updateResult = stageAPI.whiteboard.update({ elements: nextElements }, wbResult.data.id);
      if (!updateResult.success) {
        console.error('Failed to erase whiteboard element:', updateResult.error);
      }
    },
    [stageAPI],
  );

  const handleStrokeCreate = useCallback(
    (points: Array<[number, number]>) => {
      const wbResult = stageAPI.whiteboard.get();
      if (!wbResult.success || !wbResult.data) {
        return;
      }

      const strokeId = `wb-stroke-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      const segments = buildStrokeLineElements(points, strokeWidth, strokeColor, strokeId);
      if (segments.length === 0) {
        return;
      }

      const currentElements = wbResult.data.elements ?? [];
      const updateResult = stageAPI.whiteboard.update(
        { elements: [...currentElements, ...segments] },
        wbResult.data.id,
      );

      if (!updateResult.success) {
        console.error('Failed to append whiteboard stroke:', updateResult.error);
      }
    },
    [stageAPI, strokeColor, strokeWidth],
  );

  useEffect(() => {
    elementsRef.current = elements;
  }, [elements]);

  useEffect(() => {
    if (snapshotTimerRef.current) {
      clearTimeout(snapshotTimerRef.current);
      snapshotTimerRef.current = null;
    }

    if (elements.length === 0 || isClearing) {
      return;
    }

    const historyStore = useWhiteboardHistoryStore.getState();
    if (historyStore.restoredKey && historyStore.restoredKey === elementsKey) {
      historyStore.setRestoredKey(null);
      return;
    }

    snapshotTimerRef.current = setTimeout(() => {
      const current = elementsRef.current;
      if (current.length > 0) {
        useWhiteboardHistoryStore.getState().pushSnapshot(current);
      }
    }, 2000);

    return () => {
      if (snapshotTimerRef.current) {
        clearTimeout(snapshotTimerRef.current);
        snapshotTimerRef.current = null;
      }
    };
  }, [elements.length, elementsKey, isClearing]);

  useEffect(() => {
    return () => {
      if (snapshotTimerRef.current) {
        clearTimeout(snapshotTimerRef.current);
      }
    };
  }, []);

  const canvasWidth = 1000;
  const canvasHeight = 562.5;
  const padding = 24;

  const updateContainerScale = useCallback(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const { clientWidth, clientHeight } = container;
    const scaleX = clientWidth / canvasWidth;
    const scaleY = clientHeight / canvasHeight;
    setContainerScale(Math.min(scaleX, scaleY));
  }, [canvasWidth, canvasHeight]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const observer = new ResizeObserver(updateContainerScale);
    observer.observe(container);
    updateContainerScale();

    return () => observer.disconnect();
  }, [updateContainerScale]);

  const autoFitTransform = useMemo(() => {
    if (elements.length === 0) {
      return { scale: 1, tx: 0, ty: 0 };
    }

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const element of elements) {
      const bounds = getWhiteboardElementBounds(element);
      minX = Math.min(minX, bounds.minX);
      minY = Math.min(minY, bounds.minY);
      maxX = Math.max(maxX, bounds.maxX);
      maxY = Math.max(maxY, bounds.maxY);
    }

    const contentWidth = maxX - minX;
    const contentHeight = maxY - minY;
    const overflowsX = minX < 0 || maxX > canvasWidth;
    const overflowsY = minY < 0 || maxY > canvasHeight;

    if (!overflowsX && !overflowsY) {
      return { scale: 1, tx: 0, ty: 0 };
    }

    const availableWidth = canvasWidth - padding * 2;
    const availableHeight = canvasHeight - padding * 2;
    const fitScale = Math.min(1, availableWidth / contentWidth, availableHeight / contentHeight);
    const scaledWidth = contentWidth * fitScale;
    const scaledHeight = contentHeight * fitScale;

    return {
      scale: fitScale,
      tx: (canvasWidth - scaledWidth) / 2 - minX * fitScale,
      ty: (canvasHeight - scaledHeight) / 2 - minY * fitScale,
    };
  }, [canvasHeight, canvasWidth, elements, padding]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full flex items-center justify-center overflow-hidden"
    >
      <div style={{ width: canvasWidth * containerScale, height: canvasHeight * containerScale }}>
        <InteractiveWhiteboardCanvas
          autoFitTransform={autoFitTransform}
          canvasHeight={canvasHeight}
          canvasWidth={canvasWidth}
          containerScale={containerScale}
          elements={elements}
          interactionMode={interactionMode}
          isClearing={isClearing}
          onEraseAtPoint={handleEraseAtPoint}
          onStrokeCreate={handleStrokeCreate}
          readyHintText={t('whiteboard.readyHint')}
          readyText={t('whiteboard.ready')}
          resetViewText={t('whiteboard.resetView')}
          strokeColor={strokeColor}
          strokeWidth={strokeWidth}
          zoomHintText={t('whiteboard.zoomHint')}
        />
      </div>
    </div>
  );
}
