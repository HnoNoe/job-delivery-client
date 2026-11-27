```markdown
# feat(boss): 基于 CDP 旁听的 BOSS直聘 采集与投递

## 背景

现有采集/投递依赖 DrissionPage + 手工 grab 登录态，在 BOSS 上会被判定为自动化环境
（`security.html?code=36`）。直连 wapi 又因缺 `__zp_stoken__` 返回 `code:37`。

本 PR 引入一条新通道：**用本机 Chrome（真实指纹 + 真实登录态）打开页面，只旁听浏览器自己
发出的请求；投递用 CDP 注入可信鼠标事件**。全程不构造业务接口、不注入脚本、不逆向 token。

## 改动内容

### 新增

| 文件 | 说明 |
|---|---|
| `cdp_browser.py` | 通用 CDP 桥：启动（隐藏窗口）/ 附着 / 导航旁听 / 点击 / 恢复窗口 / 关闭 |
| `cdp_procs.py` | 查询并结束占用调试端口的 chrome 进程 |
| `boss_api.py` | BOSS 解析：joblist / detail / 会话、DOM 判据、风控判定 |
| `boss_crawler/` | 独立采集工具（零父仓库依赖），仿 `zhaopin_crawler/` 结构 |
| `docs/boss/` | 方案文档、运行手册、接口口径、未登录结构、端到端验证记录 |
| `.gitignore` | 排除运行时数据（logs / browser / _research / 采集产物） |

### 修改

| 文件 | 说明 |
|---|---|
| `main.py` | 新增 `browser` / `capture` / `apply` / `login-check` 四个子命令 |
| `platforms.py` | BOSS 增加 `capture` 采集配方；聊天路由修正为 `/web/geek/chat`（原 `/web/chat/index` 会被 `_security_check` 打回） |
| `pyproject.toml` | `[browser]` extra 增加 `websocket-client` |
| `README.md` | 补充 CDP 通道与 `boss_crawler` 入口 |

## 验证记录

真实账号（求职者身份）实跑：

```text
$ python main.py capture boss Python --city 101010100 --pages 1
✅ 已启动浏览器（端口 9222）
[INFO] cdp_browser: 浏览器窗口已隐藏
  第 1 页：抓到 15 条
✅ 已关闭浏览器
✅ 入库 15 个岗位

$ python main.py apply boss --limit 1 --yes
  岗位 a43cf1a0...｜python开发｜慧博云通
    页面按钮：立即沟通     投递入口：半自动（点「立即沟通」发招呼语）
    ✅ 已点击「立即沟通」于 (355, 222)
    点击后按钮：继续沟通
✅ 完成投递 1 个岗位。

（会话接口侧核对：getGeekFriendList 由 9 条变 10 条，新会话为本岗位）

$ python main.py login-check boss
[1] ✅ 登录态正常：xxx
```

风控熔断单测：

```text
URL_36   -> RAISE: 页面被跳到安全验证页（账号异常）
CODE_37  -> RAISE: 接口返回 code=37：环境异常（IP / 设备指纹被标记）
CODE_0   -> PASS(no risk)
```

## 兼容性与风险

- 新增依赖仅 `websocket-client`（放在可选 extra），不影响原有安装路径
- 默认隐藏窗口、任务结束自动关闭；`--show` / `--keep-open` 可覆盖
- 退出码：`0` 成功 / `1` 一般错误 / `2` 命中风控（便于外部调度判断）
- 未改动原有 DrissionPage 链路（`session.py` / `crawler.py` / `delivery.py`）

## 已知限制

1. 单条会话的完整消息历史尚未接入，需走 `ws.zhipin.com` WebSocket
2. 关键词搜索页处于 robots 的 `Disallow: /*?query=*` 范围，类目页通道已验证但未接入（后续 PR）
3. 图形验证码不做自动处理

## 检查清单

- [x] 真实账号端到端跑通（抓取 → 投递 → 会话核对）
- [x] 登录态失效可被检测并给出处置提示
- [x] 风控命中立即熔断，不重试
- [x] 隐藏窗口 + 任务后自动关闭
- [x] 文档齐备（架构 / 手册 / 接口口径 / 验证记录）
- [x] 未提交运行时数据与个人数据
