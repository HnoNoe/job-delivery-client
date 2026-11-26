# 智投链 · 本地桌面客户端

**无画像/匹配**的轻量客户端：**账号注册登录（本地）+ 简历字段编辑 + 浏览器自动化三件套**
（抓取岗位 / 自动投递 / 任务追踪）。简历数据结构与线上版（sicsciwoker.tech:8445）同构，
同一套解析/存储逻辑搬到本地（`resume_store.py` ↔ v1 `mydata.py`）。

## 启动

```bash
python client.py        # 或双击 启动.bat
```

## 界面五页签

| 页签 | 功能 |
|---|---|
| ① 账号 | 注册/登录/退出。PBKDF2 哈希存本地 SQLite，各账号数据互相隔离 |
| ② 简历 | L0 基础字段 + 意向岗位 + 经历（L2）增删改，保存后投递材料直接用 |
| ③ 抓取岗位 | 选平台（boss/zhilian/lagou/liepin/job51/mock）+ 关键词 + 页数，高强度校验+去重入库，2.5 秒/页限速 |
| ④ 投递 | 一键生成投递任务（自动去重）→ 批量/全部投递；安全模式默认开，只演练不真发 |
| ⑤ 任务追踪 | 当前账号全部投递任务的状态/结果实时刷新 |

## 真实平台登录（前置一步）

在浏览器手动登录平台，然后终端执行（Edge 需管理员权限）：

```bash
python main.py login <平台>    # 打开你的浏览器去登录
python main.py grab <平台>     # 从本机 cookie 库读登录态存盘
```

## 回归测试

```bash
python verify_client.py     # 账号/简历隔离/入库/建任务幂等/安全模式，20 项
python verify_db_strict.py  # 统一字段高强度校验
```

## 与主仓库的关系

本仓库 = [job-delivery-system](https://github.com/HnoNoe/job-delivery-system)（精简版 main）+ 本地账号/简历/界面层。
核心采集/投递逻辑与精简版一致，升级内核时从这里同步对应模块即可。
