```markdown
# BOSS 采集与投递：运行手册

## 环境要求

- Windows（隐藏窗口与窗口焦点用 Win32 API）
- Python 3.8+
- Google Chrome / Edge（自动探测路径，也可 `--chrome` 指定）
- 依赖：`pip install websocket-client`；导出 Excel 另需 `openpyxl`

## 一、父仓库 CLI（含投递能力）

### 1. 首次登录

```bash
python main.py browser open boss --profile "D:\path\to\chrome_profile"
```

会启动浏览器并停在登录页，扫码登录后该 profile 被记住，后续命令不用再传 `--profile`。

### 2. 查登录态

```bash
python main.py login-check boss                        # 查一次，失效退出码 1
python main.py login-check boss --interval 60 --times 10   # 轮询监测
```

### 3. 抓岗位

```bash
python main.py capture boss Python --city 101010100 --pages 1
```

输出：隐藏启动 → 抓到 15 条 → 自动关闭浏览器 → 入库。

### 4. 投递

```bash
python main.py apply boss --limit 1          # 演练：只判定不点击
python main.py apply boss --limit 1 --yes    # 真投递：点「立即沟通」
```

判定逻辑：`继续沟通` → 跳过；`立即沟通` → 点击；点击后回读按钮文案，变了才算成功。

### 参数表

| 参数 | 说明 | 默认 |
|---|---|---|
| `--port` | Chrome 调试端口 | 9222 |
| `--profile` | 浏览器 profile 目录 | 记住的值 / `runtime/browser/boss/profile` |
| `--chrome` | 浏览器可执行文件 | 自动探测 |
| `--show` | 显示窗口 | 隐藏（最小化） |
| `--keep-open` | 结束保留浏览器 | 关闭 |
| `--yes` | apply：真正点击 | 只演练 |

## 二、独立采集工具 `boss_crawler/`

零父仓库依赖，适合单独分发。

```bash
cd boss_crawler
pip install -r requirements.txt
python check_env.py            # 环境自检
python main.py login           # 登录一次
python main.py search -k Python -c 北京 -p 1
python main.py detail -n 5     # 补详情、判定投递入口
python main.py chat            # 抓 HR 沟通过列表
```

Windows 也可双击 `启动.bat` 走中文菜单。

## 三、输出物

| 文件 | 内容 |
|---|---|
| `output/BOSS直聘岗位数据.xlsx` | 9 个工作表（见下） |
| `output/BOSS直聘岗位数据.csv` | 28 列明细，UTF-8 BOM |
| `raw/岗位原始数据.jsonl` | 逐条原始记录 |
| `raw/岗位详情.jsonl` | detail 动作产物 |
| `raw/沟通列表.jsonl` | chat 动作产物 |
| `运行日志.log` | 全过程日志 |

Excel 结构：

| 工作表 | 内容 |
|---|---|
| 采集说明 | 参数、口径、合规提示 |
| 岗位明细 | 28 列，带筛选，岗位链接可点 |
| 分类统计 | 行业分布 + 柱状图 |
| 二级分类 | 公司规模分布 + 柱状图 |
| 城市统计 | 城市分布 + 柱状图 |
| 薪资分布 | 档位 / 数量 / 平均月薪 |
| 技能热度 | 技能出现岗位数 + 柱状图 |
| 公司招聘量 | 公司在招岗位数 |
| 经验与学历 | 两段表 |

薪资口径：`15-25K·14薪` → 下限 15 / 上限 25 / 中值 20 / 年薪 28 万；
`元/天`、`元/时` 不并入平均月薪，单独标注档位。

## 四、常见问题

| 现象 | 处理 |
|---|---|
| 提示「没登录」 | `python main.py browser open boss` 重新登录 |
| 「浏览器端口未就绪」 | 旧 Chrome 没退干净，结束 chrome.exe 或换 `--port 9333` |
| 抓到 0 条 | 查登录态 → 关键词/城市 → `--show` 看是否跳了安全验证 |
| 「命中风控，已停止」 | 冷却 30–60 分钟，期间不要继续抓 |
| Excel 打不开/被占用 | 会自动改存为 `原名_时间戳.xlsx` |
| 中文乱码 | 用 `启动.bat` 启动（已设 UTF-8） |
