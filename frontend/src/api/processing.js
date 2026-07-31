import { getJson, sendJson, sendWithoutBody } from "./client";

export function getProcessingJobs({ statuses = "", jobType = "", bookId = "", limit = 100 } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (statuses) params.set("statuses", statuses);
  if (jobType) params.set("job_type", jobType);
  if (bookId) params.set("book_id", String(bookId));
  return getJson(`/api/processing/jobs?${params}`, "Failed to fetch processing jobs");
}

export function queueProcessingJobs(jobType, bookIds = [], payload = {}) {
  return sendJson("/api/processing/jobs", {
    body: { job_type: jobType, book_ids: bookIds, payload },
    fallbackMessage: "Failed to queue processing",
  });
}

export function retryProcessingJob(jobId) {
  return sendWithoutBody(`/api/processing/jobs/${jobId}/retry`, {
    fallbackMessage: "Failed to retry processing job",
  });
}

export function cancelProcessingJob(jobId) {
  return sendWithoutBody(`/api/processing/jobs/${jobId}`, {
    method: "DELETE",
    fallbackMessage: "Failed to cancel processing job",
  });
}
