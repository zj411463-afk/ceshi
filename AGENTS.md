# 项目约定

- 产品目标：Windows 闲鱼指定卖家上新监控；最短 1 秒；自动创建订单，但不付款。
- 技术栈：Python、PySide6、Playwright、SQLite。Windows 使用 Edge 或 Chrome 的独立用户目录。
- UI 遵循 DESIGN.md；不引入新的前端框架。
- 首次及每次重新启动建立完整基线；不把历史商品当上新。
- 商品提交前必须持久化占位；不确定结果不得自动重试。
- 禁止增加付款、验证码绕过、隐藏自动化特征等逻辑。
- 不使用真实账号或真实订单作为自动测试夹具。
- 变更核心逻辑后运行 `.venv/bin/python -m pytest -q`；Windows 改用 `.venv\Scripts\python.exe`。
- 实盘、Windows 实机和本地模拟验证必须分别陈述，不得互相替代。
- 平台适配集中在 xianyu_monitor/browser.py。当前未完成登录账号的真实下单验收。
