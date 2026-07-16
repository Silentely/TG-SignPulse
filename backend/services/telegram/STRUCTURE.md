# telegram 拆分说明

当前 `runtime.py` 为完整实现（行为与原 `telegram.py` 一致）。
下列锚点供继续按职责迁出：

- L102: class TelegramService
- L506: async def check_account_status
- L745: async def list_account_devices
- L873: async def delete_account
- L954: async def rename_account
- L1046: async def start_login
- L1249: async def verify_login
- L1616: async def start_qr_login
- L1815: async def get_qr_login_status
