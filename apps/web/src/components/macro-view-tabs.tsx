/** 宏观工作区视图切换；与 URL search param 同步，便于分享具体视图。 */
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type MacroView = "structure" | "indicators" | "events";

const VIEW_OPTIONS: Array<{ value: MacroView; label: string }> = [
  { value: "structure", label: "市场结构" },
  { value: "indicators", label: "指标趋势" },
  { value: "events", label: "事件日历" },
];

export function MacroViewTabs({
  value,
  structure,
  indicators,
  events,
}: {
  value: MacroView;
  structure: ReactNode;
  indicators: ReactNode;
  events: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function selectView(next: string) {
    if (!VIEW_OPTIONS.some((option) => option.value === next)) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("view", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <Tabs value={value} onValueChange={selectView} className="min-w-0">
      <TabsList variant="line" className="max-w-full overflow-x-auto">
        {VIEW_OPTIONS.map((option) => (
          <TabsTrigger key={option.value} value={option.value}>
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="structure" className="mt-4">
        {structure}
      </TabsContent>
      <TabsContent value="indicators" className="mt-4">
        {indicators}
      </TabsContent>
      <TabsContent value="events" className="mt-4">
        {events}
      </TabsContent>
    </Tabs>
  );
}
