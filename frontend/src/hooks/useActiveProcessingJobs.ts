import { useQuery } from "@tanstack/react-query";

import { getProcessingJobs } from "../api/processing";
import { queryKeys } from "../lib/queryKeys";

// Queued and running processing jobs. Every caller shares one cache entry, so
// the shell's poll also serves the views that watch for jobs finishing.
function useActiveProcessingJobs(enabled = true) {
  return useQuery({
    queryKey: queryKeys.activeProcessingJobs,
    queryFn: ({ signal }) =>
      getProcessingJobs({ statuses: "queued,running", limit: 100 }, { signal }),
    enabled,
    refetchInterval: 5000,
  });
}

export default useActiveProcessingJobs;
