import { useQuery } from "@tanstack/react-query";
import { getLifecycleDefinitions } from "../api/lifecycles";

export default function useLifecycleDefinitions() {
  return useQuery({
    queryKey: ["lifecycle-definitions"],
    queryFn: getLifecycleDefinitions,
    staleTime: Infinity,
  });
}
