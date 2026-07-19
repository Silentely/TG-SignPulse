/**
 * 签到任务相关 API 域入口（从 api.ts 再导出，便于后续物理拆分）。
 */
export {
  listSignTasks,
  getSignTask,
  createSignTask,
  updateSignTask,
  deleteSignTask,
  toggleSignTaskEnabled,
  cloneSignTask,
  startSignTaskRun,
  runSignTask,
  getSignTaskRunStatus,
  listActiveSignTaskRuns,
  cancelSignTaskRun,
  getSignTaskHistory,
  getSignTaskLogs,
  getAccountChats,
  searchAccountChats,
  batchSignTasks,
} from "../api";

export type {
  SignTask,
  SignTaskRunStatus,
  ActiveRunSummary,
  CreateSignTaskRequest,
  UpdateSignTaskRequest,
  ChatInfo,
  ChatSearchResponse,
  SignTaskHistoryItem,
} from "../api";
