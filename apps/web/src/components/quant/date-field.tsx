"use client";

/**
 * 受控日期选择字段（shadcn Popover + Calendar，react-day-picker）
 * 用于回测/扫描的开始日期等需要选单日期的场景。
 * 与全站 date-picker.tsx 同一交互模式，但为受控（value/onChange 由父组件持有，不写 URL）。
 */
import { useState } from "react";
import { CalendarIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

function fmt(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function DateField({
  id,
  value,
  onChange,
  disabled,
  placeholder = "选择日期",
}: {
  id?: string;
  /** YYYY-MM-DD，空串表示未选 */
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = value ? new Date(`${value}T00:00:00`) : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            id={id}
            variant="outline"
            className="w-full justify-start gap-1.5 font-normal"
            disabled={disabled}
          />
        }
      >
        <CalendarIcon className="size-3.5 text-fg-dim" />
        {value || <span className="text-muted-foreground">{placeholder}</span>}
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={selected}
          onSelect={(d) => {
            onChange(d ? fmt(d) : "");
            setOpen(false);
          }}
          disabled={(date) => date > new Date()}
        />
      </PopoverContent>
    </Popover>
  );
}
