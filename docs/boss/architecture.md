```markdown
# BOSS直聘：CDP 旁听采集 + 可信点击投递

> 状态：可用（抓取、投递、会话列表已在真实账号上验证通过）
> 最后更新：2026-11-27

## 1. 背景：三条被否掉的路

| 尝试 | 现象 | 结论 |
|---|---|---|
| `requests` / `curl` 直连 wapi | `{"code":37,"message":"您的环境存在异常."}` | 缺 `__zp_stoken__`，且 token 绑定浏览器指纹，离线重放不可行 |
| `--headless` / 带 `--test-type=webdriver` | 直接跳 `security.html?code=36` | 无头与自动化标记必被识别 |
| DrissionPage / Selenium | 同样的自动化指纹 | 同上 |

这三条都撞在同一个点上：**BOSS 校验的是"请求由谁发出"**。
所以方案改成：**让浏览器自己发请求，我们只在旁边读；点击也由浏览器内核注入。**

## 2. 方案原理

```
本机 Chrome（真实指纹 + 真实登录态 + 持久化 profile）
   ↑ --remote-debugging-port
Python 进程
   · Page.navigate            —— 等价地址栏回车，浏览器自己去请求
   · Network.*（只读域）       —— 旁听浏览器自己发出的 XHR，读响应体
   · Runtime.evaluate         —— 只读用途：取元素坐标、按钮文案、登录态
   · Input.dispatchMouseEvent —— isTrusted=true 的真实点击
不注入脚本、不构造业务接口、不逆向 token
```

三个实测细节决定了可用性：

1. **必须整页重载**：搜索页是 SPA，内部改 query 不会重新请求 `joblist.json`；
   所以先 `Page.navigate("about:blank")` 再跳目标 URL。
2. **隐藏窗口用"最小化"而非 headless**：最小化下抓取正常（实测 12 秒/页）；
   headless 必挂。启动参数补 `--disable-background-timer-throttling` 等三项，
   防止最小化后定时器降频。
3. **点击先恢复窗口并抢焦点**：最小化时首击可能只用于激活窗口，按钮不动。

## 3. 抓取链路

```
ensure_running()  启动 Chrome（隐藏）+ profile
  → attach()      附着 page target，Network.enable
  → goto(搜索页)   about:blank → 目标 URL → 12 秒内收集事件
  → 事件配对       requestWillBeSent 记 url → loadingFinished → getResponseBody
  → parse_joblist  zpData.jobList[] → 统一中文字段
  → 熔断检查       URL 含 security.html / code=36|37 → 立即停止
  → 入库/导出      jobs 表 / JSONL / CSV / Excel
```

分页节奏：翻页间隔 **10–16 秒随机**，单轮建议 ≤5 页。
实测约 4 次搜索 + 2 次详情 + 会话抓取，**零验证码**。

## 4. 投递链路

```
goto(详情页)
  → 读 DOM 判定入口    .btn-startchat 文案：立即沟通 / 继续沟通
  → 跳过条件           已投递、已开聊、找不到按钮
  → show() + bringToFront + SetForegroundWindow
  → 算坐标             rect 中心 + scrollIntoView
  → 落点校验           elementFromPoint 必须是按钮本身或其后代
  → 派发事件           mouseMoved → mousePressed(clickCount=1) → 80ms → mouseReleased
  → 结果校验           回读按钮文案，"立即沟通" → "继续沟通" 才算成功
  → 失败兜底           Esc 关浮层重试一次；仍失败换外层 .btn-startchat-wrap
```

为什么不用 `element.click()`：JS 合成事件 `isTrusted === false`，容易被识别；
CDP 注入的鼠标事件与真人点击在页面看来一致。

## 5. 登录态管理

| 机制 | 说明 |
|---|---|
| profile 记忆 | `browser open --profile X` 记住 X（写 `runtime/browser/default_profile.json`），后续命令免参数 |
| 冲突自愈 | 调试端口被**别的 profile** 占用时，自动结束旧实例再按要求的 profile 重启，避免 `--profile` 静默失效 |
| 登录判定 | 读顶栏 DOM：出现「消息/简历」= 已登录，「登录/注册」= 未登录。不发额外请求 |
| 前置检查 | `capture` / `apply` 开跑前先查登录态，未登录直接退出 |
| 掉登录监测 | `login-check --interval 60` 轮询，失效时退出码 1 |

## 6. 风控与节流

| 特征 | 含义 | 处置 |
|---|---|---|
| URL 跳到 `/web/passport/zp/security.html?...&code=36\|37` | 被要求安全验证 | 立即停止 |
| 接口 `code=37` | 环境异常（IP/指纹被标记） | 立即停止 |
| 接口 `code=36` | 账号异常（可能出图形验证码） | 立即停止 |

原则：**不换 UA 重试、不降速重试、不换关键词绕过**。继续请求只会拉长冷却，严重会打封账号。
熔断后已抓到的数据照常落盘，退出码 `2`（0=成功，1=一般错误）。

## 7. 代码结构

| 文件 | 职责 |
|---|---|
| `cdp_browser.py` | 通用 CDP 桥：启动/隐藏/附着/导航旁听/点击/恢复窗口/关闭 |
| `cdp_procs.py` | 查询并结束占用调试端口的 chrome（隔离 PowerShell 引号问题） |
| `boss_api.py` | BOSS 解析：joblist / detail / friend、DOM 判据、风控判定 |
| `platforms.py` | `PLATFORMS["boss"]["capture"]` 采集配方；聊天路由修正 |
| `main.py` | `browser` / `capture` / `apply` / `login-check` 四个子命令 |
| `boss_crawler/` | 独立采集工具（零父仓库依赖），仿 `zhaopin_crawler/` 结构 |

## 8. 能力与限制

| 能力 | 状态 |
|---|---|
| 无人值守抓岗位 | ✅ 15 条/页，单关键词上限 300 |
| 详情 + 投递判定 | ✅ 五布尔 + 按钮文案双通道 |
| 无人值守投递 | ✅ 按钮状态变化 + 会话落库双验证 |
| 会话列表 + 消息预览 | ✅ `zprelation/friend/*` |
| 单条会话完整消息历史 | ⏳ 需接 WebSocket |
| 登录态监测 / 风控熔断 | ✅ |

已知限制：
1. 完整消息历史需要 WebSocket（`zpchat/config/ws` 已给出集群地址）
2. 关键词搜索页在 robots 的 `Disallow: /*?query=*` 范围内；类目页 `/c<city>-p<job>/` 是合规替代通道（已验证 SSR 直出岗位）
3. 图形验证码不做自动处理

## 9. 后续计划

- 接 WebSocket 做「HR 回复持续监测」
- 合并父仓库与 `boss_crawler/` 的重复实现，避免双维护
- `apply` 批量化：每日上限、失败重试、去重记账
