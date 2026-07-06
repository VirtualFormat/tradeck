import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <>
      <Skeleton className="mb-6 h-10 w-48" />
      <div className="grid grid-cols-1 gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(100px, 1fr))", gridAutoRows: "60px" }}>
        {Array.from({ length: 20 }).map((_, i) => (
          <Skeleton key={i} className="h-full w-full rounded-md" />
        ))}
      </div>
    </>
  );
}
