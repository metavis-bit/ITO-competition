'use client';

import { useState, useEffect, useRef } from 'react';
import { ImagePlus, Trash2, X, Upload, Tag } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

interface ImageItem {
  filename: string;
  keywords: string[];
  url: string;
  builtin: boolean;
}

interface ImageLibraryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ImageLibraryDialog({ open, onOpenChange }: ImageLibraryDialogProps) {
  const [images, setImages] = useState<ImageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [keywords, setKeywords] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchImages = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/v1/images/list');
      if (resp.ok) {
        const data = await resp.json();
        setImages(data.images || []);
      }
    } catch {
      // Backend may not be running
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchImages();
  }, [open]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);

    for (const file of Array.from(files)) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('keywords', keywords);

      try {
        const resp = await fetch('/v1/images/upload', {
          method: 'POST',
          body: formData,
        });
        if (resp.ok) {
          toast.success(`${file.name} 上传成功`);
        } else {
          const err = await resp.json().catch(() => ({ detail: '上传失败' }));
          toast.error(`${file.name}: ${err.detail || '上传失败'}`);
        }
      } catch {
        toast.error(`${file.name}: 网络错误`);
      }
    }

    setUploading(false);
    setKeywords('');
    fetchImages();
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDelete = async (filename: string) => {
    try {
      const resp = await fetch(`/v1/images/${filename}`, { method: 'DELETE' });
      if (resp.ok) {
        toast.success('已删除');
        setImages((prev) => prev.filter((img) => img.filename !== filename));
      }
    } catch {
      toast.error('删除失败');
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-3xl max-h-[80vh] bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-border/60 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/40">
          <div className="flex items-center gap-2">
            <ImagePlus className="size-5 text-emerald-600" />
            <h2 className="text-base font-semibold">教学素材图库</h2>
            <span className="text-xs text-muted-foreground/60">上传生物图片用于 PPT、动画和 Word 生成</span>
          </div>
          <button onClick={() => onOpenChange(false)} className="p-1.5 rounded-lg hover:bg-muted/60 transition-colors">
            <X className="size-4" />
          </button>
        </div>

        {/* Upload area */}
        <div className="px-5 py-3 border-b border-border/30 bg-muted/20">
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="text-[11px] text-muted-foreground/70 mb-1 block">
                <Tag className="size-3 inline mr-1" />
                关键词（逗号分隔，帮助 AI 自动匹配图片到相关课件页）
              </label>
              <input
                type="text"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="例如: DNA复制, 半保留, 解旋酶"
                className="w-full px-3 py-1.5 text-xs border rounded-lg bg-background focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
              />
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => handleUpload(e.target.files)}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className={cn(
                'h-8 px-4 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors',
                uploading
                  ? 'bg-muted text-muted-foreground cursor-not-allowed'
                  : 'bg-emerald-600 text-white hover:bg-emerald-700 cursor-pointer',
              )}
            >
              <Upload className="size-3.5" />
              {uploading ? '上传中...' : '上传图片'}
            </button>
          </div>
        </div>

        {/* Image grid */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="text-center text-sm text-muted-foreground/50 py-12">加载中...</div>
          ) : images.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground/50 py-12">
              暂无图片，请上传生物教学素材
            </div>
          ) : (
            <div className="grid grid-cols-3 md:grid-cols-4 gap-3">
              {images.map((img) => (
                <div
                  key={img.filename}
                  className="group relative rounded-xl border border-border/40 overflow-hidden bg-muted/20 hover:border-emerald-300 dark:hover:border-emerald-700 transition-colors"
                >
                  <div className="aspect-square relative">
                    <img
                      src={img.url}
                      alt={img.filename}
                      className="absolute inset-0 w-full h-full object-cover"
                      loading="lazy"
                    />
                  </div>
                  <div className="p-2">
                    <p className="text-[10px] font-medium truncate" title={img.filename}>
                      {img.filename}
                    </p>
                    {img.keywords.length > 0 && (
                      <p className="text-[9px] text-muted-foreground/60 truncate mt-0.5">
                        {img.keywords.join(', ')}
                      </p>
                    )}
                    {img.builtin && (
                      <span className="text-[9px] text-emerald-600 dark:text-emerald-400">内置</span>
                    )}
                  </div>
                  {/* Delete button (only for user-uploaded) */}
                  {!img.builtin && (
                    <button
                      onClick={() => handleDelete(img.filename)}
                      className="absolute top-1.5 right-1.5 p-1 rounded-md bg-red-500/80 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                      title="删除"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
