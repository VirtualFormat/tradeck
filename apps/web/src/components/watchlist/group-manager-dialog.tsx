"use client";

import { useState, type FormEvent } from "react";
import { PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react";

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
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  WatchlistStorageError,
  type WatchlistGroup,
} from "@/lib/watchlist";

interface GroupManagerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: WatchlistGroup[];
  itemCounts?: Record<string, number>;
  onAdd: (name: string) => Promise<void>;
  onRename: (id: string, name: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
}

const DEFAULT_GROUP_IDS = new Set(["watch", "core", "tactical"]);

function normalizedName(value: string): string {
  return value.trim();
}

function GroupManagerContent({
  groups,
  onAdd,
  onRename,
  onRemove,
  onClose,
}: {
  groups: WatchlistGroup[];
  onAdd: (name: string) => Promise<void>;
  onRename: (id: string, name: string) => Promise<void>;
  onRemove: (id: string) => void;
  onClose: () => void;
}) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [addError, setAddError] = useState("");
  const [editError, setEditError] = useState("");
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState(false);

  const orderedGroups = [...groups].sort(
    (left, right) => left.order - right.order
  );

  function hasDuplicateName(name: string, excludedId?: string): boolean {
    return groups.some(
      (group) =>
        group.id !== excludedId &&
        group.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase()
    );
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = normalizedName(newName);
    if (!name) {
      setAddError("请输入分组名称");
      return;
    }
    if (hasDuplicateName(name)) {
      setAddError("分组名称已存在");
      return;
    }

    setAdding(true);
    try {
      await onAdd(name);
      setNewName("");
      setAddError("");
    } catch (error: unknown) {
      setAddError(
        error instanceof WatchlistStorageError
          ? "本地存储失败，未保存"
          : "添加失败，请稍后重试"
      );
    } finally {
      setAdding(false);
    }
  }

  function startEditing(group: WatchlistGroup) {
    setEditingId(group.id);
    setEditingName(group.name);
    setEditError("");
  }

  function cancelEditing() {
    setEditingId(null);
    setEditingName("");
    setEditError("");
  }

  async function saveRename(group: WatchlistGroup) {
    const name = normalizedName(editingName);
    if (!name) {
      setEditError("请输入分组名称");
      return;
    }
    if (hasDuplicateName(name, group.id)) {
      setEditError("分组名称已存在");
      return;
    }

    if (name === group.name) {
      cancelEditing();
      return;
    }

    setRenaming(true);
    try {
      await onRename(group.id, name);
      cancelEditing();
    } catch (error: unknown) {
      setEditError(
        error instanceof WatchlistStorageError
          ? "本地存储失败，未保存"
          : "重命名失败，请稍后重试"
      );
    } finally {
      setRenaming(false);
    }
  }

  return (
    <>
      <form className="grid gap-2" onSubmit={handleAdd} noValidate>
        <Label htmlFor="new-watchlist-group">新分组</Label>
        <div className="flex gap-2">
          <Input
            id="new-watchlist-group"
            value={newName}
            maxLength={40}
            aria-invalid={Boolean(addError)}
            aria-describedby={
              addError ? "new-watchlist-group-error" : undefined
            }
            placeholder="输入分组名称"
            onChange={(event) => {
              setNewName(event.target.value);
              setAddError("");
            }}
          />
          <Button type="submit" disabled={adding}>
            {adding ? "添加中" : "添加"}
          </Button>
        </div>
        {addError ? (
          <p
            id="new-watchlist-group-error"
            className="text-xs text-destructive"
          >
            {addError}
          </p>
        ) : null}
      </form>

      <div className="grid gap-2" aria-label="现有自选分组">
        {orderedGroups.map((group) => {
          const isEditing = editingId === group.id;
          const isDefaultGroup = DEFAULT_GROUP_IDS.has(group.id);
          const canRemove = groups.length > 1 && !isDefaultGroup;

          return (
            <div
              key={group.id}
              className="grid min-h-10 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-lg border border-border p-2"
            >
              {isEditing ? (
                <div className="grid gap-2">
                  <Label htmlFor={`group-name-${group.id}`} className="sr-only">
                    重命名 {group.name}
                  </Label>
                  <Input
                    id={`group-name-${group.id}`}
                    value={editingName}
                    maxLength={40}
                    autoFocus
                    aria-invalid={Boolean(editError)}
                    aria-describedby={
                      editError ? `group-name-${group.id}-error` : undefined
                    }
                    onChange={(event) => {
                      setEditingName(event.target.value);
                      setEditError("");
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") cancelEditing();
                    }}
                  />
                  {editError ? (
                    <p
                      id={`group-name-${group.id}-error`}
                      className="text-xs text-destructive"
                    >
                      {editError}
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="min-w-0 px-1 py-1.5">
                  <p className="truncate text-sm font-medium">{group.name}</p>
                </div>
              )}

              <div className="flex shrink-0 gap-1">
                {isEditing ? (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={renaming}
                      onClick={cancelEditing}
                    >
                      取消
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      disabled={renaming}
                      onClick={() => void saveRename(group)}
                    >
                      {renaming ? "保存中" : "保存"}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`重命名 ${group.name}`}
                      onClick={() => startEditing(group)}
                    >
                      <PencilSimpleIcon />
                    </Button>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <span className="inline-flex" />
                        }
                      >
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          disabled={!canRemove}
                          aria-label={`删除 ${group.name}`}
                          onClick={() => canRemove && onRemove(group.id)}
                        >
                          <TrashIcon />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        {isDefaultGroup
                          ? "系统分组不可删除"
                          : canRemove
                            ? "删除分组"
                            : "至少保留一个分组"}
                      </TooltipContent>
                    </Tooltip>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          完成
        </Button>
      </DialogFooter>
    </>
  );
}

export function GroupManagerDialog({
  open,
  onOpenChange,
  groups,
  itemCounts = {},
  onAdd,
  onRename,
  onRemove,
}: GroupManagerDialogProps) {
  const [removeCandidate, setRemoveCandidate] = useState<WatchlistGroup | null>(
    null
  );
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const removeCount = removeCandidate
    ? (itemCounts[removeCandidate.id] ?? 0)
    : 0;

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setRemoveCandidate(null);
      setRemoveError(null);
    }
    onOpenChange(nextOpen);
  }

  async function confirmRemove() {
    if (!removeCandidate) return;
    setRemoving(true);
    setRemoveError(null);
    try {
      await onRemove(removeCandidate.id);
      setRemoveCandidate(null);
    } catch (error: unknown) {
      setRemoveError(
        error instanceof WatchlistStorageError
          ? "本地存储失败，未保存"
          : "删除失败，请稍后重试"
      );
    } finally {
      setRemoving(false);
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>管理自选分组</DialogTitle>
            <DialogDescription>
              添加或重命名分组。删除自定义分组时，标的将移至观察组。
            </DialogDescription>
          </DialogHeader>

          {open ? (
            <GroupManagerContent
              groups={groups}
              onAdd={onAdd}
              onRename={onRename}
              onRemove={(id) => {
                setRemoveError(null);
                setRemoveCandidate(
                  groups.find((group) => group.id === id) ?? null
                );
              }}
              onClose={() => handleOpenChange(false)}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(removeCandidate)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !removing) {
            setRemoveCandidate(null);
            setRemoveError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除自选分组</DialogTitle>
            <DialogDescription>
              删除“{removeCandidate?.name}”后，{removeCount}
              个标的将移至观察组，仓位、提醒和交易逻辑会保留。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            {removeError ? (
              <p role="alert" className="mr-auto text-xs text-destructive">
                {removeError}
              </p>
            ) : null}
            <Button
              type="button"
              variant="outline"
              disabled={removing}
              onClick={() => {
                setRemoveCandidate(null);
                setRemoveError(null);
              }}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={removing}
              onClick={() => void confirmRemove()}
            >
              {removing ? "删除中" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
