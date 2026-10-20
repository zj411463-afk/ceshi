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

## Cursor Cloud specific instructions

- 使用系统 Python 3.12。`python3 -m venv` 需要已安装 `python3.12-venv`。依赖装在仓库根目录 `.venv`：`.venv/bin/python -m pip install -r requirements-dev.txt`。
- 测试命令是 `.venv/bin/python -m pytest -q`。浏览器集成测试启动本机 Google Chrome（Playwright `channel=chrome`），不下载 Playwright 自带浏览器；页面和订单服务都在本机，不访问闲鱼。
- 界面可在 `QT_QPA_PLATFORM=offscreen` 下启动 `main.py`。点击「运行演示」后，约两个轮询间隔出现模拟上新和订单号 `DEMO-ORDER-0001`。演示使用内存数据库，不登录、不连接闲鱼。
- 云端环境不自动启动桌面程序。不要用真实闲鱼账号或真实订单做自动测试。
