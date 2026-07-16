"use client"

import { TrendUpIcon } from "@phosphor-icons/react"
import { Badge } from "@/components/ui/badge"

export interface TreasuryStatusBadgeProps {
  inverted: boolean
}

export function TreasuryStatusBadge({ inverted }: TreasuryStatusBadgeProps) {
  if (inverted) {
    return <Badge variant="destructive">倒挂</Badge>
  }
  return (
    <Badge variant="outline" className="text-down">
      <TrendUpIcon className="size-4" />
      正常
    </Badge>
  )
}
