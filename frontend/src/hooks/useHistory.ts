import { useQuery } from '@tanstack/react-query'
import { fetchHistory } from '../api/client'

export function useHistory(productId: number | null) {
  return useQuery({
    queryKey: ['history', productId],
    queryFn: () => fetchHistory(productId!),
    enabled: productId !== null,
    refetchInterval: 10_000,
  })
}
