"use client";

/**
 * AI 问答面板（客户端）
 * 流程：发消息(POST) → 开 EventSource(/api/ai/sessions/[id]/events) → 增量渲染
 *      text_delta 追加正文 / tool_call+tool_result 维护轨迹 / done 收尾
 * 全部经 Next 同源代理，浏览器不直连 VT
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  PaperPlaneRightIcon,
  StopIcon,
  RobotIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EmptyState } from "@/components/empty-state";
import { MarkdownView } from "@/components/ai/markdown-view";
import { ToolTrail, type ToolCall } from "@/components/ai/tool-trail";
import { cn } from "@/lib/utils";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: ToolCall[];
  streaming?: boolean;
}

interface SessionItem {
  session_id: string;
  title: string;
  updated_at: string;
}

let seq = 0;
const nid = () => `m${Date.now()}_${seq++}`;

export function ChatPanel() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, []);

  const closeStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  // 载入会话列表（fire-and-forget，.then 回调里 setState，避免 effect 内同步 setState）
  const loadSessions = useCallback(() => {
    fetch("/api/ai/sessions", { cache: "no-store" })
      .then((res) => res.json())
      .then((data) => setSessions(Array.isArray(data) ? data : []))
      .catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    loadSessions();
    return closeStream;
  }, [loadSessions, closeStream]);

  // 载入某会话的历史消息
  const openSession = useCallback(
    async (sid: string) => {
      closeStream();
      setBusy(false);
      setSessionId(sid);
      try {
        const res = await fetch(`/api/ai/sessions/${sid}/messages`, { cache: "no-store" });
        const data = await res.json().catch(() => []);
        const list: ChatMessage[] = (Array.isArray(data) ? data : [])
          .filter((m: { role?: string }) => m.role === "user" || m.role === "assistant")
          .map((m: { message_id?: string; role: string; content?: string; tool_trail?: ToolCall[] }) => ({
            id: m.message_id ?? nid(),
            role: m.role as "user" | "assistant",
            content: m.content ?? "",
            tools: Array.isArray(m.tool_trail) ? m.tool_trail : [],
          }));
        // 最后一条是空 assistant（离开前正在生成）：标记流式并续传，恢复未完成的回答
        const last = list[list.length - 1];
        const resuming = last?.role === "assistant" && !last.content;
        if (resuming) {
          last.streaming = true;
          setBusy(true);
        }
        setMessages(list);
        setTimeout(scrollToBottom, 50);
      } catch {
        setMessages([]);
      }
    },
    [closeStream, scrollToBottom]
  );

  const newSession = useCallback(() => {
    closeStream();
    setBusy(false);
    setSessionId(null);
    setMessages([]);
  }, [closeStream]);

  // 删除会话：调 VT DELETE，若删的是当前会话则清空对话区
  const deleteSession = useCallback(
    async (sid: string) => {
      try {
        await fetch(`/api/ai/sessions/${sid}`, { method: "DELETE" });
      } catch {
        // 忽略网络错误，仍刷新列表
      }
      if (sid === sessionId) {
        closeStream();
        setBusy(false);
        setSessionId(null);
        setMessages([]);
      }
      loadSessions();
    },
    [sessionId, closeStream, loadSessions]
  );

  // 订阅 SSE 流；replay=true 时重放进行中 attempt 的缓冲事件（续看离开期间的未完成回答）
  const subscribe = useCallback(
    (sid: string, replay = false) => {
      closeStream();
      const url = `/api/ai/sessions/${sid}/events${replay ? "?replay=active" : ""}`;
      const es = new EventSource(url);
      esRef.current = es;

      const patchAssistant = (fn: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === "assistant") {
              next[i] = fn(next[i]);
              break;
            }
          }
          return next;
        });
      };

      es.addEventListener("text_delta", (e) => {
        const d = JSON.parse((e as MessageEvent).data || "{}");
        patchAssistant((m) => ({ ...m, content: m.content + String(d.delta ?? "") }));
        scrollToBottom();
      });
      es.addEventListener("tool_call", (e) => {
        const d = JSON.parse((e as MessageEvent).data || "{}");
        const call: ToolCall = {
          id: String(d.call_id ?? d.tool ?? nid()),
          tool: String(d.tool ?? ""),
          arguments: (d.arguments as Record<string, unknown>) ?? {},
          status: "running",
        };
        patchAssistant((m) => ({ ...m, tools: [...(m.tools ?? []), call] }));
        scrollToBottom();
      });
      es.addEventListener("tool_result", (e) => {
        const d = JSON.parse((e as MessageEvent).data || "{}");
        patchAssistant((m) => {
          const tools = [...(m.tools ?? [])];
          for (let i = tools.length - 1; i >= 0; i--) {
            if (tools[i].tool === d.tool && tools[i].status === "running") {
              tools[i] = {
                ...tools[i],
                status: d.status === "ok" ? "ok" : "error",
                preview: String(d.preview ?? ""),
                elapsed_ms: Number(d.elapsed_ms ?? 0),
              };
              break;
            }
          }
          return { ...m, tools };
        });
      });
      const finish = () => {
        patchAssistant((m) => ({ ...m, streaming: false }));
        setBusy(false);
        closeStream();
        loadSessions();
      };
      es.addEventListener("attempt.completed", finish);
      es.addEventListener("attempt.failed", finish);
      es.addEventListener("attempt.cancelled", finish);
      es.addEventListener("done", finish);
      es.onerror = () => {
        // SSE 出错也收尾，避免卡在 streaming 态
        finish();
      };
    },
    [closeStream, loadSessions, scrollToBottom]
  );

  // 续传：打开会话后，若最后一条是空 assistant（离开前正在生成），自动 replay 恢复未完成回答
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (sessionId && last?.role === "assistant" && last.streaming) {
      subscribe(sessionId, true);
    }
    // 仅在会话/消息结构变化时判断；subscribe 稳定
  }, [sessionId, messages, subscribe]);

  const send = useCallback(async () => {
    const content = input.trim();
    if (!content || busy) return;
    setInput("");
    setBusy(true);

    try {
      let sid = sessionId;
      if (!sid) {
        const res = await fetch("/api/ai/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const data = await res.json();
        sid = data.session_id;
        if (!sid) throw new Error("no session");
        setSessionId(sid);
      }
      setMessages((prev) => [
        ...prev,
        { id: nid(), role: "user", content },
        { id: nid(), role: "assistant", content: "", tools: [], streaming: true },
      ]);
      setTimeout(scrollToBottom, 30);

      await fetch(`/api/ai/sessions/${sid}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      subscribe(sid);
    } catch {
      setBusy(false);
      setMessages((prev) => [
        ...prev,
        { id: nid(), role: "assistant", content: "服务暂时不可用，请稍后重试。" },
      ]);
    }
  }, [input, busy, sessionId, subscribe, scrollToBottom]);

  const stop = useCallback(async () => {
    if (!sessionId) return;
    closeStream();
    try {
      await fetch(`/api/ai/sessions/${sessionId}/cancel`, { method: "POST" });
    } finally {
      setBusy(false);
      setMessages((prev) =>
        prev.map((m) => (m.streaming ? { ...m, streaming: false } : m))
      );
    }
  }, [sessionId, closeStream]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex h-full min-h-0 gap-4">
      {/* 会话列表 */}
      <aside className="hidden w-52 shrink-0 flex-col rounded-md border bg-card md:flex">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-xs font-medium text-muted-foreground">分析会话</span>
          <Tooltip>
            <TooltipTrigger render={<Button variant="ghost" size="icon" className="h-6 w-6" onClick={newSession} aria-label="新建分析" />}>
              <PlusIcon className="h-4 w-4" />
            </TooltipTrigger>
            <TooltipContent>新建分析</TooltipContent>
          </Tooltip>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-0.5 p-1.5">
            {sessions.map((s) => (
              <div key={s.session_id} className="group relative">
                <Button
                  variant="ghost"
                  onClick={() => openSession(s.session_id)}
                  className={cn(
                    "h-auto w-full justify-start truncate rounded px-2 py-1.5 pr-7 text-left text-xs font-normal",
                    s.session_id === sessionId ? "bg-muted text-foreground" : "text-muted-foreground"
                  )}
                >
                  {s.title || "未命名分析"}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSession(s.session_id);
                  }}
                  aria-label="删除会话"
                  className="absolute right-0.5 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground/0 hover:bg-destructive/10 hover:text-destructive group-hover:text-muted-foreground"
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        </ScrollArea>
      </aside>

      {/* 对话区 */}
      <div className="flex min-w-0 flex-1 flex-col rounded-md border bg-card">
        <ScrollArea className="min-h-0 flex-1">
          <div className="mx-auto max-w-3xl space-y-4 p-4">
            {messages.length === 0 ? (
              <EmptyState
                title="开始一次 AI 分析"
                description="输入你的问题，例如「分析一下宁德时代最近的走势和资金面」「当前 A 股市场方向如何」"
                className="py-16"
              />
            ) : (
              messages.map((m) => (
                <div key={m.id} className={cn("flex gap-3", m.role === "user" && "justify-end")}>
                  {m.role === "assistant" && (
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10">
                      <RobotIcon className="h-4 w-4 text-primary" />
                    </div>
                  )}
                  <div
                    className={cn(
                      "min-w-0 max-w-[85%] rounded-lg px-3.5 py-2.5",
                      m.role === "user"
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted/50"
                    )}
                  >
                    {m.role === "user" ? (
                      <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                    ) : (
                      <>
                        {m.tools && m.tools.length > 0 && <ToolTrail calls={m.tools} />}
                        {m.content ? (
                          <MarkdownView content={m.content} variant="chat" streaming={m.streaming} />
                        ) : (
                          m.streaming && (
                            <span className="text-xs text-muted-foreground">正在分析…</span>
                          )
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>

        {/* 输入区 */}
        <div className="border-t p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              className="min-h-[44px] max-h-40 resize-none"
              rows={1}
            />
            {busy ? (
              <Tooltip>
                <TooltipTrigger render={<Button variant="outline" size="icon" onClick={stop} aria-label="停止" />}>
                  <StopIcon className="h-4 w-4" />
                </TooltipTrigger>
                <TooltipContent>停止</TooltipContent>
              </Tooltip>
            ) : (
              <Tooltip>
                <TooltipTrigger render={<Button size="icon" onClick={send} disabled={!input.trim()} aria-label="发送" />}>
                  <PaperPlaneRightIcon className="h-4 w-4" />
                </TooltipTrigger>
                <TooltipContent>发送</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
