/**
 * AI 分析页
 * 路由：/ai-analysis
 * 问答（Vibe-Trading agent loop 流式）+ 研究报告（swarm final_report / 影子报告）
 */
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { ChatPanel } from "@/components/ai/chat-panel";
import { ReportList } from "@/components/ai/report-list";
import { ChatCircleIcon, FileTextIcon } from "@phosphor-icons/react/dist/ssr";

export const metadata = { title: "AI 分析 · tradeck" };

export default function AiAnalysisPage() {
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4 px-4 lg:px-6">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">AI 分析</h1>
        <span className="text-xs text-muted-foreground">
          由 Vibe-Trading 研究引擎驱动
        </span>
      </div>
      <Tabs defaultValue="chat" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="w-fit">
          <TabsTrigger value="chat" className="gap-1.5">
            <ChatCircleIcon className="h-4 w-4" /> 问答
          </TabsTrigger>
          <TabsTrigger value="report" className="gap-1.5">
            <FileTextIcon className="h-4 w-4" /> 研究报告
          </TabsTrigger>
        </TabsList>
        <TabsContent value="chat" className="min-h-0 flex-1 data-[state=inactive]:hidden">
          <ChatPanel />
        </TabsContent>
        <TabsContent value="report" className="min-h-0 flex-1 data-[state=inactive]:hidden">
          <ReportList />
        </TabsContent>
      </Tabs>
    </div>
  );
}
