import { normalizeSymbol } from "@/lib/utils";

export const WATCHLIST_KEY = "tradeck-watchlist";
export const WATCHLIST_VERSION = 2 as const;
export const WATCHLIST_CHANGE_EVENT = "tradeck:watchlist-change";
const WATCHLIST_LOCK_NAME = "tradeck-watchlist";
const FALLBACK_MUTATION_ATTEMPTS = 4;

export class WatchlistConflictError extends Error {
  constructor(message = "自选数据发生并发冲突，请重试。") {
    super(message);
    this.name = "WatchlistConflictError";
  }
}

export class WatchlistStorageError extends Error {
  readonly cause: unknown;

  constructor(message = "本地存储失败，未保存", cause?: unknown) {
    super(message);
    this.name = "WatchlistStorageError";
    this.cause = cause;
  }
}

export interface WatchlistQuote {
  symbol: string;
}

export interface WatchlistGroup {
  id: string;
  name: string;
  order: number;
}

export interface WatchlistItem {
  symbol: string;
  groupId: string;
  thesis: string;
  quantity: number | null;
  averageCost: number | null;
  alertAbove: number | null;
  alertBelow: number | null;
  addedAt: string;
  updatedAt: string;
}

export interface WatchlistState {
  version: typeof WATCHLIST_VERSION;
  revision: number;
  clientId?: string;
  groups: WatchlistGroup[];
  items: WatchlistItem[];
}

export const DEFAULT_WATCHLIST_GROUPS: readonly WatchlistGroup[] = [
  { id: "watch", name: "观察", order: 0 },
  { id: "core", name: "核心", order: 1 },
  { id: "tactical", name: "交易", order: 2 },
] as const;

type WatchlistItemInput = Partial<Omit<WatchlistItem, "symbol">> & {
  symbol: string;
};

const GROUP_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DEFAULT_GROUP_IDS = new Set(
  DEFAULT_WATCHLIST_GROUPS.map((group) => group.id)
);
let watchlistClientId: string | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneDefaultGroups(): WatchlistGroup[] {
  return DEFAULT_WATCHLIST_GROUPS.map((group) => ({ ...group }));
}

function createDefaultState(): WatchlistState {
  return {
    version: WATCHLIST_VERSION,
    revision: 0,
    groups: cloneDefaultGroups(),
    items: [],
  };
}

function normalizeText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

function normalizeOrder(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : fallback;
}

function normalizeRevision(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : 0;
}

function normalizeClientId(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const clientId = value.trim();
  return clientId ? clientId.slice(0, 128) : undefined;
}

function normalizeTimestamp(value: unknown, fallback: string): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : fallback;
}

function slugifyGroupId(value: string): string {
  return value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function uniqueGroupId(base: string, usedIds: Set<string>): string {
  const normalizedBase = GROUP_ID_PATTERN.test(base) ? base : "group";
  if (!usedIds.has(normalizedBase)) return normalizedBase;

  let suffix = 2;
  while (usedIds.has(`${normalizedBase}-${suffix}`)) suffix += 1;
  return `${normalizedBase}-${suffix}`;
}

function normalizeGroups(value: unknown): WatchlistGroup[] {
  const rawGroups = Array.isArray(value) ? value : [];
  const groups: WatchlistGroup[] = [];
  const usedIds = new Set<string>();

  for (const rawGroup of rawGroups) {
    if (!isRecord(rawGroup)) continue;
    const name = normalizeText(rawGroup.name);
    const rawId = normalizeText(rawGroup.id).toLowerCase();
    if (!name || !GROUP_ID_PATTERN.test(rawId) || usedIds.has(rawId)) continue;

    groups.push({
      id: rawId,
      name,
      order: normalizeOrder(rawGroup.order, groups.length),
    });
    usedIds.add(rawId);
  }

  for (const defaultGroup of DEFAULT_WATCHLIST_GROUPS) {
    const existingIndex = groups.findIndex(
      (group) => group.id === defaultGroup.id
    );
    if (existingIndex >= 0) {
      groups[existingIndex] = {
        ...groups[existingIndex],
        name: groups[existingIndex].name || defaultGroup.name,
      };
      continue;
    }
    groups.push({ ...defaultGroup });
    usedIds.add(defaultGroup.id);
  }

  return groups
    .map((group, index) => ({ group, index }))
    .sort(
      (left, right) =>
        left.group.order - right.group.order || left.index - right.index
    )
    .map(({ group }, order) => ({ ...group, order }));
}

function normalizeItem(
  value: unknown,
  groupIds: Set<string>,
  fallbackTimestamp: string
): WatchlistItem | null {
  if (!isRecord(value) || typeof value.symbol !== "string") return null;
  const symbol = normalizeWatchlistSymbol(value.symbol);
  if (!symbol) return null;

  const requestedGroupId = normalizeText(value.groupId).toLowerCase();
  const groupId = groupIds.has(requestedGroupId) ? requestedGroupId : "watch";
  const addedAt = normalizeTimestamp(value.addedAt, fallbackTimestamp);
  const updatedAt = normalizeTimestamp(value.updatedAt, addedAt);

  return {
    symbol,
    groupId,
    thesis: normalizeText(value.thesis),
    quantity: normalizeNullableNumber(value.quantity),
    averageCost: normalizeNullableNumber(value.averageCost),
    alertAbove: normalizeNullableNumber(value.alertAbove),
    alertBelow: normalizeNullableNumber(value.alertBelow),
    addedAt,
    updatedAt,
  };
}

function normalizeState(value: unknown): WatchlistState {
  if (!isRecord(value) || value.version !== WATCHLIST_VERSION) {
    return createDefaultState();
  }

  const groups = normalizeGroups(value.groups);
  const groupIds = new Set(groups.map((group) => group.id));
  const fallbackTimestamp = new Date().toISOString();
  const items: WatchlistItem[] = [];
  const symbols = new Set<string>();

  for (const rawItem of Array.isArray(value.items) ? value.items : []) {
    const item = normalizeItem(rawItem, groupIds, fallbackTimestamp);
    if (!item || symbols.has(item.symbol)) continue;
    items.push(item);
    symbols.add(item.symbol);
  }

  const clientId = normalizeClientId(value.clientId);
  return {
    version: WATCHLIST_VERSION,
    revision: normalizeRevision(value.revision),
    ...(clientId ? { clientId } : {}),
    groups,
    items,
  };
}

function migrateLegacyWatchlist(value: unknown): WatchlistState {
  if (!Array.isArray(value)) return createDefaultState();
  const timestamp = new Date().toISOString();
  const symbols = new Set<string>();
  const items: WatchlistItem[] = [];

  for (const rawSymbol of value) {
    if (typeof rawSymbol !== "string") continue;
    const symbol = normalizeWatchlistSymbol(rawSymbol);
    if (!symbol || symbols.has(symbol)) continue;
    items.push(
      createWatchlistItem({
        symbol,
        groupId: "watch",
        addedAt: timestamp,
        updatedAt: timestamp,
      })
    );
    symbols.add(symbol);
  }

  return {
    version: WATCHLIST_VERSION,
    revision: 0,
    groups: cloneDefaultGroups(),
    items,
  };
}

export function normalizeWatchlistSymbol(input: string): string {
  return normalizeSymbol(input).trim().toUpperCase();
}

export function parseWatchlistState(value: string | null): WatchlistState {
  if (!value) return createDefaultState();
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed)
      ? migrateLegacyWatchlist(parsed)
      : normalizeState(parsed);
  } catch {
    return createDefaultState();
  }
}

export function serializeWatchlistState(state: WatchlistState): string {
  return JSON.stringify(normalizeState(state));
}

export function getWatchlistClientId(): string {
  if (watchlistClientId) return watchlistClientId;

  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    watchlistClientId = crypto.randomUUID();
  } else {
    watchlistClientId = `client-${Date.now()}-${Math.random()
      .toString(36)
      .slice(2)}`;
  }
  return watchlistClientId;
}

export function dispatchWatchlistChange(state?: WatchlistState): void {
  if (typeof window === "undefined") return;
  const detail = state ? normalizeState(state) : undefined;
  window.dispatchEvent(
    new CustomEvent<WatchlistState | undefined>(WATCHLIST_CHANGE_EVENT, {
      detail,
    })
  );
}

export function saveWatchlistState(state: WatchlistState): WatchlistState {
  const normalized = normalizeState(state);
  if (typeof window === "undefined") return normalized;

  try {
    window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(normalized));
  } catch (error: unknown) {
    throw new WatchlistStorageError(undefined, error);
  }
  dispatchWatchlistChange(normalized);
  return normalized;
}

function readStoredWatchlistState(): WatchlistState {
  if (typeof window === "undefined") return createDefaultState();
  try {
    return parseWatchlistState(window.localStorage.getItem(WATCHLIST_KEY));
  } catch {
    return createDefaultState();
  }
}

function readStoredWatchlistValue(): unknown {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(WATCHLIST_KEY);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

function hasSameWatchlistContent(
  left: WatchlistState,
  right: WatchlistState
): boolean {
  return (
    JSON.stringify({ groups: left.groups, items: left.items }) ===
    JSON.stringify({ groups: right.groups, items: right.items })
  );
}

function storageMatchesState(state: WatchlistState): boolean {
  if (typeof window === "undefined") return true;
  try {
    return (
      window.localStorage.getItem(WATCHLIST_KEY) ===
      serializeWatchlistState(state)
    );
  } catch {
    return false;
  }
}

function applyWatchlistMutation(
  current: WatchlistState,
  mutator: (state: WatchlistState) => WatchlistState,
  clientId: string
): WatchlistState {
  const candidate = normalizeState(mutator(current));
  if (hasSameWatchlistContent(candidate, current) && storageMatchesState(current)) {
    return current;
  }
  return saveWatchlistState({
    ...candidate,
    revision: current.revision + 1,
    clientId,
  });
}

function mergeFallbackMutation(
  base: WatchlistState,
  desired: WatchlistState,
  latest: WatchlistState
): WatchlistState {
  const baseGroups = new Map(base.groups.map((group) => [group.id, group]));
  const desiredGroups = new Map(
    desired.groups.map((group) => [group.id, group])
  );
  const mergedGroups = new Map(latest.groups.map((group) => [group.id, group]));

  for (const [id, baseGroup] of baseGroups) {
    const desiredGroup = desiredGroups.get(id);
    const latestGroup = mergedGroups.get(id);
    if (!desiredGroup) {
      if (latestGroup && JSON.stringify(latestGroup) === JSON.stringify(baseGroup)) {
        mergedGroups.delete(id);
      }
      continue;
    }
    if (
      JSON.stringify(desiredGroup) !== JSON.stringify(baseGroup) &&
      latestGroup &&
      JSON.stringify(latestGroup) === JSON.stringify(baseGroup)
    ) {
      mergedGroups.set(id, desiredGroup);
    }
  }
  for (const [id, desiredGroup] of desiredGroups) {
    if (!baseGroups.has(id) && !mergedGroups.has(id)) {
      mergedGroups.set(id, desiredGroup);
    }
  }

  const baseItems = new Map(base.items.map((item) => [item.symbol, item]));
  const desiredItems = new Map(
    desired.items.map((item) => [item.symbol, item])
  );
  const mergedItems = new Map(latest.items.map((item) => [item.symbol, item]));

  for (const [symbol, baseItem] of baseItems) {
    const desiredItem = desiredItems.get(symbol);
    const latestItem = mergedItems.get(symbol);
    if (!desiredItem) {
      if (latestItem?.updatedAt === baseItem.updatedAt) mergedItems.delete(symbol);
      continue;
    }
    if (
      desiredItem.updatedAt !== baseItem.updatedAt &&
      latestItem?.updatedAt === baseItem.updatedAt
    ) {
      mergedItems.set(symbol, desiredItem);
    }
  }
  for (const [symbol, desiredItem] of desiredItems) {
    if (!baseItems.has(symbol) && !mergedItems.has(symbol)) {
      mergedItems.set(symbol, desiredItem);
    }
  }

  const groupIds = new Set(mergedGroups.keys());
  const groups = [...mergedGroups.values()]
    .sort((left, right) => left.order - right.order)
    .map((group, order) => ({ ...group, order }));
  return normalizeState({
    ...latest,
    groups,
    items: [...mergedItems.values()].map((item) =>
      groupIds.has(item.groupId) ? item : { ...item, groupId: "watch" }
    ),
  });
}

async function mutateWithoutWebLock(
  mutator: (state: WatchlistState) => WatchlistState,
  clientId: string
): Promise<WatchlistState> {
  let lastSaved = readStoredWatchlistState();

  // Web Locks 不可用时，每次冲突都从最新快照重放领域操作，避免整份旧状态覆盖。
  for (let attempt = 0; attempt < FALLBACK_MUTATION_ATTEMPTS; attempt += 1) {
    const base = readStoredWatchlistState();
    const desired = normalizeState(mutator(base));
    if (hasSameWatchlistContent(desired, base) && storageMatchesState(base)) {
      return base;
    }
    lastSaved = applyWatchlistMutation(base, () => desired, clientId);
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));

    const observed = readStoredWatchlistState();
    if (
      observed.revision === lastSaved.revision &&
      observed.clientId === clientId
    ) {
      return observed;
    }

    const merged = mergeFallbackMutation(base, desired, observed);
    lastSaved = applyWatchlistMutation(observed, () => merged, clientId);
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    const mergedObserved = readStoredWatchlistState();
    if (
      mergedObserved.revision === lastSaved.revision &&
      mergedObserved.clientId === clientId
    ) {
      return mergedObserved;
    }
  }

  throw new WatchlistConflictError();
}

export async function mutateWatchlistState(
  mutator: (state: WatchlistState) => WatchlistState
): Promise<WatchlistState> {
  if (typeof window === "undefined") {
    const current = createDefaultState();
    return normalizeState(mutator(current));
  }

  const clientId = getWatchlistClientId();
  if ("locks" in navigator && navigator.locks) {
    return navigator.locks.request(WATCHLIST_LOCK_NAME, async () => {
      const latest = readStoredWatchlistState();
      return applyWatchlistMutation(latest, mutator, clientId);
    });
  }

  return mutateWithoutWebLock(mutator, clientId);
}

export async function migrateLegacyWatchlistStateAtomically(
  legacyState: WatchlistState
): Promise<WatchlistState> {
  const normalizedLegacy = normalizeState(legacyState);

  return mutateWatchlistState((latest) => {
    const storedValue = readStoredWatchlistValue();
    if (
      latest.revision > 0 ||
      (isRecord(storedValue) && storedValue.version === WATCHLIST_VERSION) ||
      !Array.isArray(storedValue)
    ) {
      return latest;
    }

    const existingSymbols = new Set(
      latest.items.map((item) => item.symbol)
    );
    const groupIds = new Set(latest.groups.map((group) => group.id));
    const migratedItems = normalizedLegacy.items
      .filter((item) => !existingSymbols.has(item.symbol))
      .map((item) =>
        groupIds.has(item.groupId) ? item : { ...item, groupId: "watch" }
      );

    return {
      ...latest,
      items: [...latest.items, ...migratedItems],
    };
  });
}

export function createWatchlistItem(
  input: string | WatchlistItemInput,
  groupId = "watch"
): WatchlistItem {
  const source: WatchlistItemInput =
    typeof input === "string" ? { symbol: input, groupId } : input;
  const timestamp = new Date().toISOString();
  const addedAt = normalizeTimestamp(source.addedAt, timestamp);
  const updatedAt = normalizeTimestamp(source.updatedAt, timestamp);

  return {
    symbol: normalizeWatchlistSymbol(source.symbol),
    groupId: GROUP_ID_PATTERN.test(normalizeText(source.groupId).toLowerCase())
      ? normalizeText(source.groupId).toLowerCase()
      : "watch",
    thesis: normalizeText(source.thesis),
    quantity: normalizeNullableNumber(source.quantity),
    averageCost: normalizeNullableNumber(source.averageCost),
    alertAbove: normalizeNullableNumber(source.alertAbove),
    alertBelow: normalizeNullableNumber(source.alertBelow),
    addedAt,
    updatedAt:
      Date.parse(updatedAt) < Date.parse(addedAt) ? addedAt : updatedAt,
  };
}

export function upsertWatchlistItem(
  state: WatchlistState,
  input: string | WatchlistItemInput,
  updates: Partial<Omit<WatchlistItem, "symbol" | "addedAt">> = {}
): WatchlistState {
  const normalizedState = normalizeState(state);
  const source: WatchlistItemInput =
    typeof input === "string" ? { symbol: input, ...updates } : input;
  const symbol = normalizeWatchlistSymbol(source.symbol);
  if (!symbol) return normalizedState;

  const existing = normalizedState.items.find((item) => item.symbol === symbol);
  const groupIds = new Set(normalizedState.groups.map((group) => group.id));
  const requestedGroupId = normalizeText(
    source.groupId ?? existing?.groupId ?? "watch"
  ).toLowerCase();
  const timestamp = new Date().toISOString();
  const candidate = createWatchlistItem({
    ...existing,
    ...source,
    symbol,
    groupId: groupIds.has(requestedGroupId) ? requestedGroupId : "watch",
    addedAt: existing?.addedAt ?? source.addedAt ?? timestamp,
    updatedAt: timestamp,
  });

  return {
    ...normalizedState,
    items: existing
      ? normalizedState.items.map((item) =>
          item.symbol === symbol ? candidate : item
        )
      : [...normalizedState.items, candidate],
  };
}

export function removeWatchlistItem(
  state: WatchlistState,
  symbol: string
): WatchlistState {
  const normalizedState = normalizeState(state);
  const normalizedSymbol = normalizeWatchlistSymbol(symbol);
  return {
    ...normalizedState,
    items: normalizedState.items.filter(
      (item) => item.symbol !== normalizedSymbol
    ),
  };
}

export function reconcileWatchlistState(
  state: WatchlistState,
  validSymbols: WatchlistQuote[]
): WatchlistState {
  const normalizedState = normalizeState(state);
  const valid = new Set(
    validSymbols
      .filter(
        (item): item is WatchlistQuote =>
          isRecord(item) && typeof item.symbol === "string"
      )
      .map((item) => normalizeWatchlistSymbol(item.symbol))
      .filter(Boolean)
  );
  return {
    ...normalizedState,
    items: normalizedState.items.filter((item) => valid.has(item.symbol)),
  };
}

export function addWatchlistGroup(
  state: WatchlistState,
  name: string,
  preferredId?: string
): WatchlistState {
  const normalizedState = normalizeState(state);
  const normalizedName = normalizeText(name);
  if (!normalizedName) return normalizedState;

  const usedIds = new Set(normalizedState.groups.map((group) => group.id));
  const preferredSlug = slugifyGroupId(preferredId ?? normalizedName);
  const id = uniqueGroupId(preferredSlug || "group", usedIds);
  return {
    ...normalizedState,
    groups: [
      ...normalizedState.groups,
      { id, name: normalizedName, order: normalizedState.groups.length },
    ],
  };
}

export function renameWatchlistGroup(
  state: WatchlistState,
  groupId: string,
  name: string
): WatchlistState {
  const normalizedState = normalizeState(state);
  const normalizedId = normalizeText(groupId).toLowerCase();
  const normalizedName = normalizeText(name);
  if (!normalizedName) return normalizedState;

  return {
    ...normalizedState,
    groups: normalizedState.groups.map((group) =>
      group.id === normalizedId ? { ...group, name: normalizedName } : group
    ),
  };
}

export function removeWatchlistGroup(
  state: WatchlistState,
  groupId: string
): WatchlistState {
  const normalizedState = normalizeState(state);
  const normalizedId = normalizeText(groupId).toLowerCase();
  if (
    normalizedState.groups.length <= 1 ||
    DEFAULT_GROUP_IDS.has(normalizedId) ||
    !normalizedState.groups.some((group) => group.id === normalizedId)
  ) {
    return normalizedState;
  }

  const timestamp = new Date().toISOString();
  return {
    ...normalizedState,
    groups: normalizedState.groups
      .filter((group) => group.id !== normalizedId)
      .map((group, order) => ({ ...group, order })),
    items: normalizedState.items.map((item) =>
      item.groupId === normalizedId
        ? { ...item, groupId: "watch", updatedAt: timestamp }
        : item
    ),
  };
}

export function getWatchlistSymbols(state: WatchlistState): string[] {
  return normalizeState(state).items.map((item) => item.symbol);
}

export function parseWatchlist(value: string | null): string[] {
  return getWatchlistSymbols(parseWatchlistState(value));
}

export function reconcileWatchlist(
  requested: string[],
  validSymbols: WatchlistQuote[]
): string[] {
  const valid = new Set(
    validSymbols.map((item) => normalizeWatchlistSymbol(item.symbol))
  );
  return requested
    .map(normalizeWatchlistSymbol)
    .filter((symbol, index, symbols) => {
      return (
        Boolean(symbol) &&
        valid.has(symbol) &&
        symbols.indexOf(symbol) === index
      );
    });
}

export async function validateWatchlistSymbols(
  symbols: string[]
): Promise<WatchlistQuote[]> {
  if (symbols.length === 0) return [];
  const response = await fetch(
    `/api/search/validate?symbols=${encodeURIComponent(symbols.join(","))}`,
    { cache: "no-store" }
  );
  if (!response.ok) {
    throw new Error("symbol validation failed");
  }
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as WatchlistQuote[]) : [];
}

export async function fetchValidQuotes<T extends WatchlistQuote>(
  symbols: string[]
): Promise<T[]> {
  if (symbols.length === 0) return [];
  const response = await fetch(
    `/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}&_t=${Date.now()}`,
    { cache: "no-store" }
  );
  if (!response.ok) return [];
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as T[]) : [];
}

export async function validateWatchlistSymbol(
  input: string
): Promise<{ symbol: string; valid: boolean }> {
  const symbol = normalizeWatchlistSymbol(input);
  if (!symbol) return { symbol, valid: false };

  const validSymbols = await validateWatchlistSymbols([symbol]);
  return {
    symbol,
    valid: validSymbols.some((item) => item.symbol === symbol),
  };
}
