"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  WatchlistStorageError,
  type WatchlistGroup,
  type WatchlistItem,
} from "@/lib/watchlist";

interface WatchlistEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  item: WatchlistItem | null;
  groups: WatchlistGroup[];
  onSave: (
    item: WatchlistItem,
    expectedUpdatedAt: string
  ) => Promise<boolean | string>;
}

interface EditorFormState {
  groupId: string;
  quantity: string;
  averageCost: string;
  alertAbove: string;
  alertBelow: string;
  thesis: string;
}

type NumericField = "quantity" | "averageCost" | "alertAbove" | "alertBelow";
type FormErrors = Partial<Record<NumericField | "alerts", string>>;

const EMPTY_FORM: EditorFormState = {
  groupId: "",
  quantity: "",
  averageCost: "",
  alertAbove: "",
  alertBelow: "",
  thesis: "",
};

const NUMBER_LABELS: Record<NumericField, string> = {
  quantity: "持仓数量",
  averageCost: "平均成本",
  alertAbove: "上破提醒",
  alertBelow: "下破提醒",
};

function toInputValue(value: number | null): string {
  return value == null ? "" : String(value);
}

function formFromItem(
  item: WatchlistItem | null,
  groups: WatchlistGroup[]
): EditorFormState {
  if (!item) return EMPTY_FORM;
  const hasCurrentGroup = groups.some((group) => group.id === item.groupId);

  return {
    groupId: hasCurrentGroup ? item.groupId : (groups[0]?.id ?? ""),
    quantity: toInputValue(item.quantity),
    averageCost: toInputValue(item.averageCost),
    alertAbove: toInputValue(item.alertAbove),
    alertBelow: toInputValue(item.alertBelow),
    thesis: item.thesis,
  };
}

function parseOptionalNumber(
  value: string,
  field: NumericField,
  errors: FormErrors
): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) {
    errors[field] = `${NUMBER_LABELS[field]}必须是非负有限数字`;
    return null;
  }
  return parsed;
}

function NumberField({
  id,
  label,
  value,
  error,
  helper,
  onChange,
}: {
  id: NumericField;
  label: string;
  value: string;
  error?: string;
  helper?: string;
  onChange: (value: string) => void;
}) {
  const descriptionId = error
    ? `${id}-error`
    : helper
      ? `${id}-helper`
      : undefined;

  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min="0"
        step="any"
        inputMode="decimal"
        value={value}
        aria-invalid={Boolean(error)}
        aria-describedby={descriptionId}
        onChange={(event) => onChange(event.target.value)}
      />
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : helper ? (
        <p id={`${id}-helper`} className="text-xs text-muted-foreground">
          {helper}
        </p>
      ) : null}
    </div>
  );
}

function WatchlistEditorForm({
  item,
  groups,
  onSave,
  onCancel,
}: {
  item: WatchlistItem;
  groups: WatchlistGroup[];
  onSave: (
    item: WatchlistItem,
    expectedUpdatedAt: string
  ) => Promise<boolean | string>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<EditorFormState>(() =>
    formFromItem(item, groups)
  );
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function updateField(field: keyof EditorFormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setSubmitError(null);
    if (field in NUMBER_LABELS) {
      setErrors((current) => ({
        ...current,
        [field]: undefined,
        alerts:
          field === "alertAbove" || field === "alertBelow"
            ? undefined
            : current.alerts,
      }));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors: FormErrors = {};
    const quantity = parseOptionalNumber(form.quantity, "quantity", nextErrors);
    const averageCost = parseOptionalNumber(
      form.averageCost,
      "averageCost",
      nextErrors
    );
    const alertAbove = parseOptionalNumber(
      form.alertAbove,
      "alertAbove",
      nextErrors
    );
    const alertBelow = parseOptionalNumber(
      form.alertBelow,
      "alertBelow",
      nextErrors
    );

    if (
      alertAbove != null &&
      alertBelow != null &&
      alertBelow >= alertAbove
    ) {
      nextErrors.alerts = "下破提醒必须低于上破提醒";
    }

    if (Object.values(nextErrors).some(Boolean)) {
      setErrors(nextErrors);
      return;
    }

    setSaving(true);
    setSubmitError(null);
    try {
      const result = await onSave(
        {
          ...item,
          groupId: form.groupId || item.groupId,
          quantity,
          averageCost,
          alertAbove,
          alertBelow,
          thesis: form.thesis.trim(),
          updatedAt: new Date().toISOString(),
        },
        item.updatedAt
      );
      if (result === true) {
        onCancel();
        return;
      }
      setSubmitError(
        typeof result === "string" ? result : "保存失败，请稍后重试"
      );
    } catch (error: unknown) {
      setSubmitError(
        error instanceof WatchlistStorageError
          ? "本地存储失败，未保存"
          : "保存失败，请稍后重试"
      );
    } finally {
      setSaving(false);
    }
  }

  const showCostSuggestion =
    Boolean(form.quantity.trim()) && !form.averageCost.trim();

  return (
    <form className="grid gap-4" onSubmit={handleSubmit} noValidate>
      <div className="grid gap-2">
        <Label htmlFor="watchlist-symbol">股票代码</Label>
        <Input
          id="watchlist-symbol"
          value={item.symbol}
          readOnly
          aria-readonly="true"
          className="font-mono"
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="watchlist-group">分组</Label>
        <Select
          value={form.groupId}
          onValueChange={(value) => updateField("groupId", value ?? "")}
          disabled={groups.length === 0}
        >
          <SelectTrigger id="watchlist-group" className="w-full">
            <SelectValue placeholder="选择分组" />
          </SelectTrigger>
          <SelectContent>
            {[...groups]
              .sort((left, right) => left.order - right.order)
              .map((group) => (
                <SelectItem key={group.id} value={group.id}>
                  {group.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          id="quantity"
          label="持仓数量"
          value={form.quantity}
          error={errors.quantity}
          onChange={(value) => updateField("quantity", value)}
        />
        <NumberField
          id="averageCost"
          label="平均成本"
          value={form.averageCost}
          error={errors.averageCost}
          helper={
            showCostSuggestion ? "已有持仓数量，建议补充平均成本" : undefined
          }
          onChange={(value) => updateField("averageCost", value)}
        />
        <NumberField
          id="alertAbove"
          label="上破提醒"
          value={form.alertAbove}
          error={errors.alertAbove}
          onChange={(value) => updateField("alertAbove", value)}
        />
        <NumberField
          id="alertBelow"
          label="下破提醒"
          value={form.alertBelow}
          error={errors.alertBelow}
          onChange={(value) => updateField("alertBelow", value)}
        />
      </div>

      {errors.alerts ? (
        <p role="alert" className="text-xs text-destructive">
          {errors.alerts}
        </p>
      ) : null}

      <div className="grid gap-2">
        <Label htmlFor="watchlist-thesis">交易逻辑</Label>
        <Textarea
          id="watchlist-thesis"
          value={form.thesis}
          rows={4}
          placeholder="记录买入依据、失效条件和后续观察点"
          onChange={(event) => updateField("thesis", event.target.value)}
        />
      </div>

      {submitError ? (
        <p role="alert" className="text-xs text-destructive">
          {submitError}
        </p>
      ) : null}

      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          disabled={saving}
          onClick={onCancel}
        >
          取消
        </Button>
        <Button type="submit" disabled={groups.length === 0 || saving}>
          {saving ? "保存中" : "保存"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function WatchlistEditorDialog({
  open,
  onOpenChange,
  item,
  groups,
  onSave,
}: WatchlistEditorDialogProps) {
  function handleOpenChange(nextOpen: boolean) {
    onOpenChange(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑自选</DialogTitle>
          <DialogDescription>
            记录仓位、交易逻辑与价格提醒，不会自动提交交易。
          </DialogDescription>
        </DialogHeader>

        {item ? (
          <WatchlistEditorForm
            key={`${item.symbol}:${item.updatedAt}`}
            item={item}
            groups={groups}
            onSave={onSave}
            onCancel={() => handleOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
