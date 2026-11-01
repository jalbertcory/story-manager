import { api, unwrap, requestInit } from "./client";
import type { Body, RequestOptions } from "./client";
type JobRequest = Body<"/api/processing/jobs", "post">;
export const getProcessingJob = (jobId: number, options?: RequestOptions) =>
  unwrap(
    api.GET("/api/processing/jobs/{job_id}", {
      ...requestInit(options),
      params: { path: { job_id: jobId } },
    }),
  );
export function getProcessingJobs(
  {
    statuses = "",
    jobType = "",
    bookId = "",
    limit = 100,
  }: {
    statuses?: string;
    jobType?: string;
    bookId?: number | "";
    limit?: number;
  } = {},
  options?: RequestOptions,
) {
  return unwrap(
    api.GET("/api/processing/jobs", {
      ...requestInit(options),
      params: {
        query: {
          ...(statuses ? { statuses } : {}),
          ...(jobType ? { job_type: jobType } : {}),
          ...(bookId ? { book_id: bookId } : {}),
          limit,
        },
      },
    }),
    "Failed to fetch processing jobs",
  );
}
export function queueProcessingJobs(body: JobRequest) {
  return unwrap(
    api.POST("/api/processing/jobs", { body }),
    "Failed to queue processing",
  );
}

export function retryProcessingJob(jobId: number) {
  return unwrap(
    api.POST("/api/processing/jobs/{job_id}/retry", {
      params: { path: { job_id: jobId } },
    }),
    "Failed to retry processing job",
  );
}
export function cancelProcessingJob(jobId: number) {
  return unwrap(
    api.DELETE("/api/processing/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
    }),
    "Failed to cancel processing job",
  );
}
