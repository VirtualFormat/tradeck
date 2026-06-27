import { z } from 'zod';

export const DATA_SOURCE_TYPES = ['mock', 'binance', 'rss', 'mock-feed', 'http-json'] as const;
export type DataSourceType = (typeof DATA_SOURCE_TYPES)[number];

export type ConnectorStatus =
  | 'idle'
  | 'starting'
  | 'running'
  | 'stopped'
  | 'error'
  | 'unknown';

/** The `config` JSONB payload (= ConnectorConfig minus id). */
export const DataSourceConfigSchema = z.object({
  symbols: z.array(z.string()).default([]),
  options: z.record(z.string(), z.unknown()).optional(),
});
export type DataSourceConfigJson = z.infer<typeof DataSourceConfigSchema>;

export const DataSourceSchema = z.object({
  id: z.string().min(1),
  type: z.enum(DATA_SOURCE_TYPES),
  name: z.string().min(1),
  enabled: z.boolean(),
  config: DataSourceConfigSchema,
  createdAt: z.number(),
  updatedAt: z.number(),
});
export type DataSource = z.infer<typeof DataSourceSchema>;

/** List item = row + live connector status. */
export type DataSourceWithHealth = DataSource & { status: ConnectorStatus };

export const CreateDataSourceSchema = z.object({
  id: z
    .string()
    .min(1)
    .regex(/^[a-z0-9][a-z0-9-]*$/, 'id must be a lowercase slug'),
  type: z.enum(DATA_SOURCE_TYPES),
  name: z.string().min(1),
  enabled: z.boolean().default(true),
  config: DataSourceConfigSchema,
});
export type CreateDataSourceDto = z.infer<typeof CreateDataSourceSchema>;

/** PATCH: mutable fields optional; id is immutable (it is the PK/source). */
export const UpdateDataSourceSchema = CreateDataSourceSchema.partial().omit({ id: true });
export type UpdateDataSourceDto = z.infer<typeof UpdateDataSourceSchema>;
