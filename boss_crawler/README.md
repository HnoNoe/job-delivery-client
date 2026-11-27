# BOSS直聘 岗位采集工具（CDP 旁听版）

用你自己电脑上的 Chrome 抓 BOSS直聘 的岗位，**不需要装 Playwright / Selenium**，
只需要一个 `websocket-client`。浏览器窗口默认隐藏（最小化），任务结束自动关闭。

---

## 一、它怎么工作的

不是"模拟请求"，也不是"爬虫脚本暴力请求"，而是：

1. 本程序拉起你的 Chrome，加一个调试端口（`--remote-debugging-port`）
2. 让浏览器自己去打开 BOSS 的搜索页（地址栏输入等价的操作）
3. **只旁听**浏览器自己发出的网络请求，从响应里把岗位字段读出来
4. 不构造业务接口、不注入脚本、不改请求参数 —— 浏览器发什么，我们读什么

这样带的是真实浏览器指纹和真实登录态，比 headless + 伪造 UA 稳得多。

---

## 二、三分钟上手

```bash
# 1. 装依赖（只有一个必需）
pip install -r requirements.txt

# 2. 环境自检
python check_env.py

# 3. 登录一次（会弹出浏览器窗口，扫码登录；登录态存在本文件夹 browser_data/ 里）
python main.py login

# 4. 开始抓（默认 6 关键词 × 8 城市 × 1 页）
python main.py search

# 5. 结果在 output/ 里：BOSS直聘岗位数据.xlsx / .csv
```

Windows 用户也可以直接双击 **启动.bat**，走中文菜单。

---

## 三、常用命令

```bash
python main.py search -k "Python,Java" -c "北京,上海" -p 2   # 自定义关键词/城市/页数
python main.py search -k Python --show                        # 想看着它跑（显示窗口）
python main.py search -k Python --keep-open                   # 抓完不关浏览器
python main.py detail -n 5                                    # 给前 5 条补详情、判定投递入口
python main.py chat                                           # 抓"沟通过"的 HR 会话列表
python main.py check                                          # 环境自检
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `-k / --keywords` | 搜索关键词，逗号分隔 | `config.DEFAULT_KEYWORDS` |
| `-c / --cities` | 城市，逗号分隔 | `config.DEFAULT_CITIES` |
| `-p / --pages` | 每个组合翻几页 | 1（最多 20） |
| `-m / --max` | 最多抓多少条（去重后） | 300 |
| `--port` | Chrome 调试端口 | 9222 |
| `--profile` | 浏览器 profile 目录 | `browser_data/` |
| `--chrome` | 浏览器可执行文件 | 自动找 |
| `--show` | 显示窗口 | 隐藏（最小化） |
| `--keep-open` | 结束保留浏览器 | 关 |
| `--open` | 结束打开 output 目录 | 不开 |

---

## 四、输出

```
raw/岗位原始数据.jsonl          逐条原始记录（程序再处理用）
raw/岗位详情.jsonl              detail 动作的产物
raw/沟通列表.jsonl              chat 动作的产物
output/BOSS直聘岗位数据.csv
output/BOSS直聘岗位数据.xlsx     岗位明细 + 采集说明
运行日志.log                     全过程日志
```

字段：岗位名称、单位名称、薪资、城市、区域、经验、学历、行业、公司规模、HR、HR职位、技能、岗位链接。

---

## 五、文件说明

| 文件 | 作用 |
|---|---|
| `main.py` | 入口，五个动作：check / login / search / detail / chat |
| `browser.py` | CDP 浏览器驱动（启动、隐藏、旁听、点击、关闭） |
| `parser.py` | 解析接口响应和页面状态 |
| `exporter.py` | 导出 JSONL / CSV / Excel |
| `config.py` | 城市编码、默认关键词、节流参数 |
| `menu.py` | 中文菜单（启动.bat 调它） |
| `check_env.py` | 环境自检 |
| `utils.py` | 编码、日志、杂项 |

---

## 六、注意事项（请务必看）

1. **频率**：两次翻页之间默认随机等 10–16 秒（`config.MIN_DELAY` / `MAX_DELAY`），别调太小。BOSS 风控很严，触发后会出现安全验证页，甚至掉登录。
2. **不要用 headless**：实测 BOSS 会直接判定环境异常（跳 `security.html` / `code=36`），本工具也刻意不加 `--headless`。
3. **窗口隐藏不等于无痕**：默认最小化是为了不打扰你，不是绕过检测。
4. **仅供个人求职分析**：不要商用、不要转卖数据、不要拿去做批量骚扰。
5. **掉登录**：跑之前会自检登录态；若提示未登录，`python main.py login` 重新扫码即可。

---

## 七、常见问题

**Q：提示"没登录"？**
先 `python main.py login`。登录态存在 `browser_data/`，删掉这个文件夹就等于退出登录。

**Q：提示"浏览器端口未就绪"？**
可能是上一次的 Chrome 没退干净。任务管理器结束 chrome.exe，或换端口 `--port 9333`。

**Q：抓不到岗位（0 条）？**
按顺序查：登录态 → 关键词/城市写对没 → 是否触发了安全验证（`--show` 看一眼窗口）。

**Q：想要更多条数？**
BOSS 搜索接口单关键词最多 300 条（15 条/页）。调 `-p` 翻页、加关键词、加城市。

---

## 八、风控熔断（重要）

抓取过程中会实时检测两种风控特征，**一旦命中立刻停止，不重试**：

| 特征 | 说明 |
|---|---|
| 页面跳到 `/web/passport/zp/security.html?...&code=36\|37` | 被要求安全验证 |
| 接口返回 `{"code":37}` / `{"code":36}` | 37=环境异常（IP/指纹被标记），36=账号异常（可能出图形验证码） |

命中后的输出长这样：

```
🛑 命中风控，已立即停止：接口返回 code=37：环境异常（IP / 设备指纹被标记）
   建议：立刻停手，冷却 30–60 分钟再试；期间不要刷新、不要继续抓。
```

此时**已抓到的数据仍会保存**，退出码为 `2`（成功是 0，其它错误是 1），方便外部脚本判断。

设计原则：不换 UA 重试、不降速重试、不换关键词绕过 —— 继续请求只会加长冷却，严重会把号打封。

