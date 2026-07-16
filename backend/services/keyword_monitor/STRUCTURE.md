# keyword_monitor 拆分说明

当前 `runtime.py` 为完整实现（行为与原 `keyword_monitor.py` 一致）。
下列锚点供继续按职责迁出：

- L40: class TerminalAIActionError
- L75: class KeywordMonitorRule
- L530: class KeywordMonitorService
- L1198: async def _execute_ai_action
- L2102: async def restart_from_tasks
- L2269: def get_keyword_monitor_service
