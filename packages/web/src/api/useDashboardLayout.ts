import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { DashboardLayout } from '@tradeck/shared';
import { fetchLayout, saveLayout } from './http';

const KEY = ['dashboard-layout'];

export function useDashboardLayout() {
  return useQuery({ queryKey: KEY, queryFn: fetchLayout, staleTime: Infinity });
}

export function useSaveLayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (layout: DashboardLayout) => saveLayout(layout),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });
}
