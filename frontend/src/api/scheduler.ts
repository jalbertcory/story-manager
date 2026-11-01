import { api, unwrap, requestInit } from "./client";
import type { Body, RequestOptions } from "./client";
export const getSchedulerStatus = (options?: RequestOptions) =>
  unwrap(api.GET("/api/scheduler/status", requestInit(options)));
export const getSchedulerJob = (options?: RequestOptions) =>
  unwrap(api.GET("/api/scheduler/job", requestInit(options)));
export const getSchedulerHistory = (
  { limit = 20, offset = 0 } = {},
  options?: RequestOptions,
) =>
  unwrap(
    api.GET("/api/scheduler/history", {
      ...requestInit(options),
      params: { query: { limit, offset } },
    }),
  );
export const getSchedulerTaskLogs = (id: number, options?: RequestOptions) =>
  unwrap(
    api.GET("/api/scheduler/history/{task_id}/logs", {
      ...requestInit(options),
      params: { path: { task_id: id } },
    }),
  );
export const triggerScheduler = () =>
  unwrap(api.POST("/api/scheduler/trigger"));
export const updateSchedulerConfig = (
  body: Body<"/api/scheduler/config", "put">,
) => unwrap(api.PUT("/api/scheduler/config", { body }));
