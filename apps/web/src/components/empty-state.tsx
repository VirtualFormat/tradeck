/**
 * 空状态组件（借鉴 TickFlow EmptyState）
 */
import { type LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {Icon && (
        <Icon className="mb-3 h-10 w-10 text-muted/50" />
      )}
      <h3 className="text-sm font-medium text-fg-dim">{title}</h3>
      {description && (
        <p className="mt-1 text-xs text-muted">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
