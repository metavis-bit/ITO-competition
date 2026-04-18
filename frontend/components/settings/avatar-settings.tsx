'use client';

import { useState, useRef } from 'react';
import { Upload, Trash2, ImageIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { AvatarRenderer, setCustomAvatar } from '@/components/avatar';
import { useSettingsStore } from '@/lib/store/settings';
import { useUserProfileStore } from '@/lib/store/user-profile';
import { toast } from 'sonner';

const CUSTOM_AVATAR_KEY = 'avatar_custom_image';
const MAX_SIZE_BYTES = 512 * 1024; // 512KB after base64

export function AvatarSettings() {
  const [preview, setPreview] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    try {
      return localStorage.getItem(CUSTOM_AVATAR_KEY);
    } catch {
      return null;
    }
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const avatarVlmUseGlobalModelConfig = useUserProfileStore((s) => s.avatarVlmUseGlobalModelConfig);
  const avatarVlmApiKey = useUserProfileStore((s) => s.avatarVlmApiKey);
  const avatarVlmBaseUrl = useUserProfileStore((s) => s.avatarVlmBaseUrl);
  const avatarVlmModel = useUserProfileStore((s) => s.avatarVlmModel);
  const avatarVoiceEnabled = useUserProfileStore((s) => s.avatarVoiceEnabled);
  const setAvatarVlmUseGlobalModelConfig = useUserProfileStore((s) => s.setAvatarVlmUseGlobalModelConfig);
  const setAvatarVlmApiKey = useUserProfileStore((s) => s.setAvatarVlmApiKey);
  const setAvatarVlmBaseUrl = useUserProfileStore((s) => s.setAvatarVlmBaseUrl);
  const setAvatarVlmModel = useUserProfileStore((s) => s.setAvatarVlmModel);
  const setAvatarVoiceEnabled = useUserProfileStore((s) => s.setAvatarVoiceEnabled);
  const providerId = useSettingsStore((s) => s.providerId);
  const modelId = useSettingsStore((s) => s.modelId);
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const providerConfig = providersConfig?.[providerId];
  const globalModelProviderName = providerConfig?.name || providerId;
  const globalModelBaseUrl =
    providerConfig?.baseUrl || providerConfig?.serverBaseUrl || providerConfig?.defaultBaseUrl || '';
  const globalModelApiKeyConfigured = !!providerConfig?.apiKey?.trim();

  const handleFile = (file: File) => {
    if (!file.type.startsWith('image/')) {
      toast.error('请上传图片文件 (PNG / JPG / GIF / WebP)');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      if (dataUrl.length > MAX_SIZE_BYTES) {
        // Resize via canvas
        const img = new Image();
        img.onload = () => {
          const canvas = document.createElement('canvas');
          const maxDim = 400;
          let w = img.width;
          let h = img.height;
          if (w > maxDim || h > maxDim) {
            const ratio = Math.min(maxDim / w, maxDim / h);
            w = Math.round(w * ratio);
            h = Math.round(h * ratio);
          }
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d')!;
          ctx.drawImage(img, 0, 0, w, h);
          const compressed = canvas.toDataURL('image/png', 0.85);
          setCustomAvatar(compressed);
          setPreview(compressed);
          toast.success('自定义形象已设置');
        };
        img.src = dataUrl;
      } else {
        setCustomAvatar(dataUrl);
        setPreview(dataUrl);
        toast.success('自定义形象已设置');
      }
    };
    reader.readAsDataURL(file);
  };

  const handleRemove = () => {
    setCustomAvatar(null);
    setPreview(null);
    toast.success('已恢复默认形象');
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold mb-1">数字人形象设置</h3>
        <p className="text-xs text-muted-foreground">
          上传自定义卡通形象替换默认数字人。支持 PNG / JPG / GIF / WebP，建议正方形透明底图。
        </p>
      </div>

      <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-3">
        <div className="rounded-md bg-background/80 px-3 py-2 border border-border/50 space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-medium">头像多模态解析模型</div>
              <p className="text-[11px] text-muted-foreground">
                用于解析数字人形象并匹配声线，可直接跟随页面语言模型配置。
              </p>
            </div>
            <Switch
              checked={avatarVlmUseGlobalModelConfig}
              onCheckedChange={setAvatarVlmUseGlobalModelConfig}
            />
          </div>

          {avatarVlmUseGlobalModelConfig ? (
            <div className="rounded-md border border-border/50 bg-muted/20 px-2.5 py-2 text-[11px] space-y-1">
              <div>
                当前来源：
                {' '}
                <span className="font-medium">{globalModelProviderName}</span>
                {' / '}
                <span className="font-medium">{modelId || '(未选择模型)'}</span>
              </div>
              <div className="text-muted-foreground break-all">
                Base URL:
                {' '}
                {globalModelBaseUrl || '(未配置)'}
              </div>
              <div className="text-muted-foreground">
                API Key:
                {' '}
                {globalModelApiKeyConfigured ? '已配置' : '未配置'}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-foreground/85">多模态 API Key</label>
                <Input
                  value={avatarVlmApiKey}
                  onChange={(e) => setAvatarVlmApiKey(e.target.value)}
                  placeholder="输入用于头像解析的 API Key"
                  className="h-8 text-xs"
                  type="password"
                />
              </div>
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-foreground/85">多模态 Base URL</label>
                <Input
                  value={avatarVlmBaseUrl}
                  onChange={(e) => setAvatarVlmBaseUrl(e.target.value)}
                  placeholder="如：https://dashscope.aliyuncs.com/compatible-mode/v1"
                  className="h-8 text-xs"
                />
              </div>
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-foreground/85">多模态模型 ID</label>
                <Input
                  value={avatarVlmModel}
                  onChange={(e) => setAvatarVlmModel(e.target.value)}
                  placeholder="如：qwen2.5-vl-72b-instruct"
                  className="h-8 text-xs"
                />
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between rounded-md bg-background/80 px-3 py-2 border border-border/50">
          <div>
            <div className="text-xs font-medium">启用数字人声音</div>
            <p className="text-[11px] text-muted-foreground">关闭后仅显示字幕，不自动播放音频。</p>
          </div>
          <Switch checked={avatarVoiceEnabled} onCheckedChange={setAvatarVoiceEnabled} />
        </div>
      </div>

      {/* Preview */}
      <div className="flex items-start gap-6">
        <div className="flex flex-col items-center gap-2">
          <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider font-medium">当前形象</div>
          <div className="rounded-2xl border border-border/50 bg-gray-50 dark:bg-gray-900/50 p-3">
            <AvatarRenderer
              avatarState="idle"
              subtitle={null}
              audioUrl={null}
              autoPlay={false}
              size={140}
              showSubtitle={false}
              isSpeaking={false}
              hasError={false}
            />
          </div>
        </div>

        {/* Upload area */}
        <div className="flex-1 flex flex-col gap-3">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = '';
            }}
          />

          <button
            onClick={() => fileRef.current?.click()}
            className="flex flex-col items-center justify-center gap-2 h-32 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-700 hover:border-emerald-400 dark:hover:border-emerald-600 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 transition-colors cursor-pointer"
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const file = e.dataTransfer.files?.[0];
              if (file) handleFile(file);
            }}
          >
            <Upload className="w-6 h-6 text-gray-400" />
            <span className="text-xs text-muted-foreground">点击或拖拽上传自定义形象</span>
          </button>

          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => fileRef.current?.click()}
              className="flex-1"
            >
              <ImageIcon className="w-3.5 h-3.5 mr-1.5" />
              选择图片
            </Button>
            {preview && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleRemove}
                className="text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                恢复默认
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Tips */}
      <div className="rounded-lg bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/50 dark:border-emerald-800/30 p-3 space-y-1">
        <div className="text-xs font-medium text-emerald-700 dark:text-emerald-400">提示</div>
        <ul className="text-[11px] text-emerald-600/80 dark:text-emerald-400/60 space-y-0.5 list-disc list-inside">
          <li>推荐使用透明背景 (PNG) 的卡通形象，效果更好</li>
          <li>建议图片尺寸 300x300 ~ 600x600 像素</li>
          <li>上传后所有数字人状态将使用同一形象，通过动画区分状态</li>
          <li>形象保存在浏览器本地，清除浏览器数据后需重新上传</li>
        </ul>
      </div>
    </div>
  );
}
