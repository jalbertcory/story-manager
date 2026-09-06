import { api, unwrap } from "./client";
import type { Body } from "./client";
export const getSchedulerStatus = () =>
  unwrap(api.GET("/api/scheduler/status"));
export const getSchedulerJob = () => unwrap(api.GET("/api/scheduler/job"));
export const getSchedulerHistory = ({ limit = 20, offset = 0 } = {}) =>
  unwrap(
    api.GET("/api/scheduler/history", { params: { query: { limit, offset } } }),
  );
export const getSchedulerTaskLogs = (id: number) =>
  unwrap(
    api.GET("/api/scheduler/history/{task_id}/logs", {
      params: { path: { task_id: id } },
    }),
  );
export const triggerScheduler = () =>
  unwrap(api.POST("/api/scheduler/trigger"));
export const updateSchedulerConfig = (
  body: Body<"/api/scheduler/config", "put">,
) => unwrap(api.PUT("/api/scheduler/config", { body }));
