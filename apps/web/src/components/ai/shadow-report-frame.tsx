"use client";

/**
 * 影子账户报告视图（整页 HTML/PDF）
 * HTML 用 iframe sandbox 隔离样式/脚本；PDF 提供下载与新窗口
 */
import { FilePdfIcon, ArrowSquareOutIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

export function ShadowReportFrame({ shadowId }: { shadowId: string }) {
  const html = `/api/ai/shadow-reports/${encodeURIComponent(shadowId)}?format=html`;
  const pdf = `/api/ai/shadow-reports/${encodeURIComponent(shadowId)}?format=pdf`;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2 p-3">
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          render={<a href={pdf} download />}
        >
          <FilePdfIcon className="mr-1 h-4 w-4" /> 下载 PDF
        </Button>
        <Button
          variant="ghost"
          size="sm"
          render={<a href={html} target="_blank" rel="noopener noreferrer" />}
        >
          <ArrowSquareOutIcon className="mr-1 h-4 w-4" /> 新窗口打开
        </Button>
      </div>
      <iframe
        src={html}
        sandbox="allow-same-origin"
        title="影子账户报告"
        className="min-h-0 flex-1 rounded-md border bg-background"
      />
    </div>
  );
}
