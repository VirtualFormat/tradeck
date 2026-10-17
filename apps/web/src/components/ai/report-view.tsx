"use client";

/**
 * Markdown 研究报告视图（swarm / run 的 final_report）
 * 完整渲染（非流式），挂 KaTeX/highlight；报告头含 preset/状态/耗时/下载
 */
import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownView } from "@/components/ai/markdown-view";

interface ReportViewProps {
  presetName?: string;
  status?: string;
  createdAt?: string;
  report: string;
}

export function ReportView({ presetName, status, createdAt, report }: ReportViewProps) {
  const download = () => {
    const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${presetName ?? "report"}-${createdAt ?? ""}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        {presetName && <Badge variant="secondary">{presetName}</Badge>}
        {status && (
          <Badge variant={status === "completed" ? "outline" : "destructive"}>{status}</Badge>
        )}
        {createdAt && (
          <span className="text-xs text-muted-foreground">{createdAt.slice(0, 10)}</span>
        )}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={download}>
          <DownloadSimpleIcon className="mr-1 h-4 w-4" /> 下载 md
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl p-6">
          <MarkdownView content={report} variant="report" />
        </div>
      </div>
    </div>
  );
}
