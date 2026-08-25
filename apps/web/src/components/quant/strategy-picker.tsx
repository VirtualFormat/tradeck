"use client";

/**
 * 策略选择器 + schema 驱动的参数表单（Tab1 回测 / Tab2 扫描共享）
 * 参数表单由策略 params schema 自动生成：float/int → number 输入，bool → Checkbox，select → Select
 */
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { ParamValues, StrategyDef } from "./types";

const SOURCE_LABEL: Record<string, string> = {
  builtin: "内置",
  ai: "AI",
  mining: "挖掘",
};

function sourceBadgeVariant(source: string) {
  if (source === "builtin") return "secondary" as const;
  if (source === "ai") return "default" as const;
  return "outline" as const;
}

interface StrategyPickerProps {
  strategies: StrategyDef[];
  strategyId: string;
  onStrategyChange: (id: string) => void;
  disabled?: boolean;
}

// preset Select 的 onValueChange 签名为 (value: string | null, eventDetails)，
// 统一包一层把 null 归一为空串后再回调（类型对齐 + 防御空值）。
function useSelectChange(cb: (v: string) => void) {
  return (v: string | null) => cb(v ?? "");
}

export function StrategyPicker({
  strategies,
  strategyId,
  onStrategyChange,
  disabled,
}: StrategyPickerProps) {
  const selected = strategies.find((s) => s.id === strategyId) ?? null;
  return (
    <div className="space-y-2">
      <div className="space-y-1.5">
        <Label htmlFor="quant-strategy">策略</Label>
        <Select
          value={strategyId}
          onValueChange={useSelectChange(onStrategyChange)}
          disabled={disabled || strategies.length === 0}
        >
          <SelectTrigger id="quant-strategy" className="w-full">
            <SelectValue placeholder="选择策略" />
          </SelectTrigger>
          <SelectContent>
            {strategies.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {selected && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={sourceBadgeVariant(selected.source)}>
            {SOURCE_LABEL[selected.source] ?? selected.source}
          </Badge>
          {selected.tags.map((tag) => (
            <Badge key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
        </div>
      )}
      {selected?.description && (
        <p className="text-xs text-muted-foreground">{selected.description}</p>
      )}
    </div>
  );
}

interface StrategyParamsFormProps {
  strategy: StrategyDef | null;
  values: ParamValues;
  onChange: (values: ParamValues) => void;
  disabled?: boolean;
}

export function StrategyParamsForm({
  strategy,
  values,
  onChange,
  disabled,
}: StrategyParamsFormProps) {
  const params = strategy?.params ?? [];
  if (!strategy || params.length === 0) return null;

  const setValue = (id: string, value: string) =>
    onChange({ ...values, [id]: value });

  return (
    <div className="grid grid-cols-2 gap-3">
      {params.map((p) => {
        const fieldId = `quant-param-${strategy.id}-${p.id}`;
        if (p.type === "bool") {
          return (
            <div key={p.id} className="col-span-2 flex items-center gap-2">
              <Checkbox
                id={fieldId}
                checked={values[p.id] === "true"}
                onCheckedChange={(checked) =>
                  setValue(p.id, checked === true ? "true" : "false")
                }
                disabled={disabled}
              />
              <Label htmlFor={fieldId} className="font-normal">
                {p.label ?? p.id}
              </Label>
            </div>
          );
        }
        if (p.type === "select" && p.options && p.options.length > 0) {
          return (
            <div key={p.id} className="space-y-1.5">
              <Label htmlFor={fieldId}>{p.label ?? p.id}</Label>
              <Select
                value={values[p.id] ?? ""}
                onValueChange={(v: string | null) => setValue(p.id, v ?? "")}
                disabled={disabled}
              >
                <SelectTrigger id={fieldId} className="w-full">
                  <SelectValue placeholder="选择" />
                </SelectTrigger>
                <SelectContent>
                  {p.options.map((opt) => (
                    <SelectItem key={String(opt)} value={String(opt)}>
                      {String(opt)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }
        return (
          <div key={p.id} className="space-y-1.5">
            <Label htmlFor={fieldId}>{p.label ?? p.id}</Label>
            <Input
              id={fieldId}
              type="number"
              value={values[p.id] ?? ""}
              min={p.min}
              max={p.max}
              step={p.step ?? (p.type === "int" ? 1 : "any")}
              onChange={(e) => setValue(p.id, e.target.value)}
              disabled={disabled}
            />
          </div>
        );
      })}
    </div>
  );
}
