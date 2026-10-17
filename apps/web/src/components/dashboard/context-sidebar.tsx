import { DashboardNews } from "@/components/dashboard/dashboard-news";
import { EventCenter } from "@/components/dashboard/event-center";

export function ContextSidebar() {
  return (
    <aside
      aria-labelledby="context-sidebar-title"
      className="flex min-w-0 flex-col gap-3.5 lg:min-h-[43.75rem]"
    >
      <div className="flex h-[1.875rem] items-center">
        <h2
          id="context-sidebar-title"
          className="text-[13px] font-medium text-fg-dim"
        >
          资讯 · 事件 · 日历
        </h2>
      </div>
      <EventCenter />
      <DashboardNews />
    </aside>
  );
}
