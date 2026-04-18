'use client';

import { motion } from 'motion/react';
import { Check, RotateCcw } from 'lucide-react';
import type { BackendTeachingIntent } from '@/lib/types/backend';
import { cn } from '@/lib/utils';

interface IntentSummaryCardProps {
  intent: BackendTeachingIntent;
  onConfirm: () => void;
  onReset: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  subject: '学科',
  topic: '课题',
  teaching_goal: '教学目标',
  target_audience: '授课对象',
  grade_level: '年级',
  page_range: '页数范围',
  key_focus: '重点内容',
  difficulties: '难点内容',
  game_types: '游戏类型',
  special_requirements: '特殊要求',
};

export function IntentSummaryCard({ intent, onConfirm, onReset }: IntentSummaryCardProps) {
  const entries = Object.entries(intent).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  );

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="mx-4 my-3 rounded-xl border border-emerald-200/60 dark:border-emerald-800/40 bg-emerald-50/50 dark:bg-emerald-950/20 p-4"
    >
      <div className="flex items-center gap-2 mb-3">
        <div className="size-6 rounded-full bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
          <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
          教学意图已确认
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
        {entries.map(([key, value]) => (
          <div key={key} className="flex gap-1.5">
            <span className="text-muted-foreground/70 shrink-0">
              {FIELD_LABELS[key] || key}:
            </span>
            <span className="text-foreground/80 truncate">
              {Array.isArray(value) ? value.join('、') : String(value)}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-emerald-200/40 dark:border-emerald-800/30">
        <button
          onClick={onConfirm}
          className={cn(
            'flex-1 h-8 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5',
            'bg-emerald-600 text-white hover:bg-emerald-700 transition-colors',
          )}
        >
          <Check className="size-3.5" />
          确认并生成课件
        </button>
        <button
          onClick={onReset}
          className="h-8 px-3 rounded-lg text-xs text-muted-foreground hover:bg-muted/60 transition-colors flex items-center gap-1"
        >
          <RotateCcw className="size-3" />
          重新沟通
        </button>
      </div>
    </motion.div>
  );
}
