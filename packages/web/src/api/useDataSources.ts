import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { CreateDataSourceDto, UpdateDataSourceDto } from '@tradeck/shared';
import {
  createDataSource,
  deleteDataSource,
  fetchDataSources,
  updateDataSource,
} from './http';

const KEY = ['datasources'];

export function useDataSources() {
  return useQuery({ queryKey: KEY, queryFn: fetchDataSources, refetchInterval: 5000 });
}

export function useCreateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dto: CreateDataSourceDto) => createDataSource(dto),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, dto }: { id: string; dto: UpdateDataSourceDto }) =>
      updateDataSource(id, dto),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDataSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
