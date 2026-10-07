# 闲鱼指定卖家上新监控

Windows 桌面首版：指定卖家、最短 1 秒轮询、每日监控时段、发现上新后自动创建订单并拦截付款。也提供仅监控和隔离的演示模式。

**交付状态：源码、Windows 安装/打包脚本及本地测试已完成；尚未完成登录账号的实盘验收，也未生成经过 Windows 实机验证的 EXE。** 当前环境为 macOS。测试访问闲鱼真实主页时返回“非法访问，请使用正常浏览器”，不能将本地测试通过理解为已经可以稳定实盘抢单。

## Windows 使用

1. 将整个文件夹解压到 Windows 10/11 的普通可写目录。
2. 安装 **Python 3.11 或 3.12（64 位）**，安装时勾选 `Add python.exe to PATH`。电脑需已安装 Microsoft Edge 或 Google Chrome。
3. 双击 `install-windows.bat` 安装依赖；这一步需要联网。
4. 双击 `start-windows.bat` 打开软件。
5. 可以先点“运行演示”，约 2 个轮询间隔后会出现模拟上新及模拟订单，不登录、不连接闲鱼、不污染真实记录。
6. 选择浏览器，点击“① 打开闲鱼，扫码登录”，在独立浏览器中手动登录。完成后点软件中的“完成登录”。请提前在闲鱼设置默认收货地址。
7. 输入卖家数字 ID、网页版主页链接，或从闲鱼复制的整段卖家分享文字。
8. 设置检查间隔，选择“仅监控上新”或“自动拍下，不付款”，点击“② 开始监控”。

本次提供的“云南小木郎”分享链接已解析为卖家 ID `2141274515`，软件已预填。该 ID 来自分享跳转参数；登录后的卖家展示信息仍需核对。

网页版主页：<https://www.goofish.com/personal?userId=2141274515>。

## 监控与拍单规则

- 一次运行监控一个卖家。自动拍下模式会处理该卖家本轮新出现的所有商品，每个商品数量为 1；没有关键词或价格筛选。
- **1 秒是两轮开始时间的最短设置，不是保证 1 秒内发现并抢到商品。** 每轮完整读取卖家列表；网络、商品数量、网站响应会影响实际耗时。慢请求不会叠加成并发请求。
- 每次启动、重启或进入新监控时段，先读取完整列表建立基线，已有商品不拍。停止、休眠或非监控时段出现的商品会在下一次基线中跳过，不追拍。
- 时段使用电脑本地时间，可设置 `23:00–02:00` 这样的跨午夜时段。停止时间不包含在时段内。电脑休眠或程序关闭后不会继续监控。
- 商品 ID 写入 SQLite 去重。在提交订单前持久化占位；重启、页面重复出现、请求结果不明，都不会自动重试同一商品。
- 列表缺页、返回结构变化、登录失效、平台验证、网络失败都会暂停；不会将错误页面当作空列表，也不会尝试绕过验证。
- 创建订单前重新核对商品卖家，只有网页版支持交易的商品才继续。收货地址、SKU、特殊协议或其他需要选择的流程不做猜测，无法明确识别时暂停。
- 只点击明确的“确认购买 / 提交订单 / 确认下单”按钮。订单请求必须对应目标商品、数量为 1，且一次尝试最多放行一次。
- 在浏览器发出请求时拦截已识别支付接口和支付宝域名；下单阶段还阻止未列入允许清单的接口。拿到创建接口返回的订单号才记录“已拍下 · 未付款”，随后关闭订单页，不进入支付流程。
- “结果待核对 / 需要核对”可能代表请求已经发出但结果未收到，必须到闲鱼“我买到的”确认。软件不自动重拍，也不自动取消订单。
- 仅监控模式发现并记录过的商品，随后切换到自动拍下模式不会补拍。

## Windows EXE 打包

在 Windows 上双击 `build-windows.bat`：安装开发依赖、运行测试，再用 PyInstaller 打包。

产物：

```text
dist\XianyuMonitor\XianyuMonitor.exe
dist\XianyuMonitor-Windows.zip
```

将整个 ZIP 分发并完整解压，不能只复制 EXE。打包后的目标机器无需安装 Python，但仍需 Edge 或 Chrome。当前项目没有预制 Windows EXE；macOS 本机无法用 PyInstaller 直接产出 Windows 应用。

代码推送到 GitHub 后，仓库的 **Actions → Build Windows EXE** 会在 Windows 云端自动测试和打包。成功后可在该次运行页面的 Artifacts 区域下载 `XianyuMonitor-Windows`，解压后得到包含 EXE 的完整程序包。

## 数据位置

Windows：`%LOCALAPPDATA%\XianyuSellerMonitor`。软件“数据目录”按钮可直接打开。

- `settings.json`：卖家与监控设置。
- `monitor.sqlite3`：商品去重、订单结果，界面显示最近 200 条非基线记录。
- `activity.log`：本地运行日志，按大小轮换。
- `browser-profile`：软件专用浏览器登录状态，请勿分享该目录。

演示模式使用内存数据库，不连接闲鱼。软件不会上传这些数据。重新安装源码不影响数据目录；不要随意删除去重数据库。

## 开发与验证

```bash
python -m venv .venv
# Windows: .venv\Scripts\python；macOS: .venv/bin/python
python -m pip install -r requirements-dev.txt
python -m pytest -q
python main.py
```

以上命令中的 `python` 应使用虚拟环境中的解释器。浏览器集成测试使用 Windows 的 Edge 或 macOS 的 Chrome，测试页面和订单服务均在本地，不访问真实闲鱼账号。

验证覆盖：首次基线、重启去重、不确定订单不重试、停止、仅监控、1 秒下限、跨午夜时段、商品身份/数量校验、未知接口拦截、真实浏览器中的模拟订单创建及付款阻断。界面在 macOS 下以两种桌面尺寸进行离屏渲染检查。

仍待验收：Windows 安装/打包与实机运行；登录后卖家商品列表；有意购买的真实新商品从确认订单到待付款状态。平台页面或接口变化可能需要适配 `xianyu_monitor/browser.py`。

## 实现依据

2026-10-07 检查的闲鱼公开网页资源为 `xy-site/0.0.176`：

- [卖家主页脚本](https://g.alicdn.com/idle-pc/xy-site/0.0.176/js/p_personal-index.js)：卖家身份、商品卡片及分页结构。
- [商品详情脚本](https://g.alicdn.com/idle-pc/xy-site/0.0.176/js/p_item-index.js)：卖家身份及网页版交易支持字段。
- [创建订单脚本](https://g.alicdn.com/idle-pc/xy-site/0.0.176/js/p_create-order-index.js)：创建订单与后续支付调用分离，创建成功返回 `bizOrderIdStr`。
- [Playwright 浏览器文档](https://playwright.dev/python/docs/browsers)：使用已安装的 Edge / Chrome。
- [PyInstaller 文档](https://pyinstaller.org/en/stable/usage.html)：需在目标系统分别打包。

接口名称和字段来自公开页面代码，并非已获得官方稳定 API 承诺。软件通过登录后的网页 SDK 读取列表，通过可见订单页提交，不伪造登录凭证、不实现验证绕过。
