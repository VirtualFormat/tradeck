import { z } from 'zod';

/** A single grid item (react-grid-layout compatible). */
export const LayoutItemSchema = z.object({
  i: z.string(),
  x: z.number().int().nonnegative(),
  y: z.number().int().nonnegative(),
  w: z.number().int().positive(),
  h: z.number().int().positive(),
  minW: z.number().int().positive().optional(),
  minH: z.number().int().positive().optional(),
});
export type LayoutItem = z.infer<typeof LayoutItemSchema>;

export const DashboardLayoutSchema = z.object({
  items: z.array(LayoutItemSchema),
});
export type DashboardLayout = z.infer<typeof DashboardLayoutSchema>;
