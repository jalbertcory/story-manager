import { useQuery } from "@tanstack/react-query";
import { getLifecycleDefinitions } from "../api/lifecycles";
import { queryKeys } from "../lib/queryKeys";

export default function useLifecycleDefinitions() {
  return useQuery({
    queryKey: queryKeys.lifecycleDefinitions,
    queryFn: getLifecycleDefinitions,
    staleTime: Infinity,
  });
}
