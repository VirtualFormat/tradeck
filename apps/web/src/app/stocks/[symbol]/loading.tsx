/**
 * 个股详情页 loading 状态
 * 渲染时显示骨架屏，避免 "rendering" 卡住无反馈
 */
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <>
      {/* 标题区骨架 */}
      <div className="mb-6 flex items-start justify-between border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-5 w-16" />
          </div>
          <div className="mt-2 flex gap-3">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-3 w-12" />
          </div>
        </div>
        <div className="text-right">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="ml-auto mt-1 h-4 w-16" />
        </div>
      </div>

      {/* 内容区骨架 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* K 线图骨架 */}
        <div className="lg:col-span-2">
          <Skeleton className="h-72 w-full rounded-lg" />
        </div>
        {/* 指标骨架 */}
        <div>
          <Skeleton className="h-72 w-full rounded-lg" />
        </div>
      </div>

      {/* 财报骨架 */}
      <div className="mt-4">
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>
    </>
  );
}
