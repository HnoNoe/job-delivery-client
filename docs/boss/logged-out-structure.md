# BOSS直聘 未登录状态站点结构实测

> 抓取时间：2026-11-26 17:15~17:22（Asia/Shanghai）
> 抓取方：本机直连（Node fetch，非浏览器）+ Firecrawl keyless（云端 IP）
> 出口 IP 状态：已被风控标记（所有内容页 302 → security.html）

## 1. 未登录可见性分级（实测状态码）

| 路径 | 状态 | 内容 | 结论 |
|---|---|---|---|
| `/` 首页 | 200 | 528 KB 完整 HTML，1501 个链接 | **公开可抓**，含完整分类树、职位列表入口、公司入口 |
| `/job_detail/<encryptJobId>.html` | **302 → security.html** | 0 字节 | 当前 IP 被拦；正常应服务端渲染 |
| `/gongsi/<companyId>.html` | **302 → security.html** | 0 字节 | 同上 |
| `/c<city>-p<job>`（类目落地页） | **302 → security.html** | 0 字节 | 同上 |
| `/beijing` 等城市页 | 301 → `/beijing/` | 0 字节 | 规范化重定向 |
| `/web/geek/job?query=…` | 200 | **8.9 KB SPA 空壳** | 无服务端数据，全靠 wapi |
| `/wapi/zpgeek/search/joblist.json` | 200 | `{"code":37,"message":"您的环境存在异常."}` | **接口层风控**，带 seed/ts/name 挑战 |
| `/robots.txt` | 200 | 1 KB | 见第 5 节 |
| `/sitemap.xml` | 404 | — | 无 sitemap |

## 2. URL 家族（来自首页 1501 个锚点统计）

| 家族 | 数量 | 形态 |
|---|---|---|
| 职位详情 | 108 | `/job_detail/<encryptJobId>.html` |
| 公司主页 | 101 | `/gongsi/<companyId>.html` |
| 类目落地页 | ~1000+ | `/c<9位城市码>-p<6位职位码>`（如 `/c100010000-p100109` = 全国·Python） |
| 城市页 | 26 | `/beijing` `/shanghai` `/hangzhou` … |
| 其它入口 | — | `/school`（校招）、`/recommend`、`/overseas`、`/accessible_job`、`/jianzhi`、`/returnee_jobs`、`/desktop` |
| SPA 路由 | 14 | `/web/geek/*`、`/web/boss/*` |
| 协议页 | 5 | `/agreement/*` |

## 3. 分类编码体系（已落成字典）

首页直接暴露「城市码 × 职位码」二维矩阵：

- 城市码前缀：`c100010000` = 全国；另有 25 个单城市页
- 职位码：**833 个**（`p100101`=Java、`p100109`=Python、`p100116`=Golang、`p101313`=高性能计算工程师…）
- 交叉形态：`/c100010000-p100109` = 全国范围 Python 岗

完整映射见 `boss-category-map.json`（jobCodeToName 833 条 / cityCodes 26 条）。

## 4. 风控构成（未登录也生效）

1. `browser-check-v2.js`（`img.bosszhipin.com`）——浏览器指纹探测
2. `warlockdata.min.2.2.15.js`（`static.zhipin.com/assets/sdk/warlock/`）——风控数据 SDK
3. `/web/passport/zp/security.html` 挑战页，参数结构：
   ```
   ?seed=<base64 服务端种子>&name=35b7bed2&ts=<毫秒时间戳>
   &callbackUrl=<原始路径>&appName=zhipin_geek_spa_web&code=36|37&srcReferer=<来源>
   ```
   - `code=37`：环境异常（接口返回同源）
   - `code=36`：账号异常（登录态下触发，会升级为图形验证码）
4. 接口层：无 `__zp_stoken__` 时 wapi 一律 `code:37`，不返回业务数据

## 5. robots.txt 关键约束

```
User-agent: *
Disallow: /*?query=*      Disallow: /*?ka=*
Disallow: /*.js*          Disallow: /job_detail/l*.html
Disallow: *?position=*    Disallow: *?city=*
Disallow: *?experience=*  Disallow: *?salary=*
Disallow: *?degree=*      Disallow: /web/boss/*
Disallow: /brand/*        Disallow: /sem/*
Disallow: /wapi/zppassport/get/zpToken*
```
含义：**带查询参数的搜索页不在允许抓取范围**；`/job_detail/<id>.html` 本身允许（`l*` 前缀除外）。

## 6. 已观测到的 wapi 端点

| 端点 | 用途 |
|---|---|
| `/wapi/zpgeek/search/joblist.json` | 职位列表（登录态 + token 才返回数据） |
| `/wapi/zpgeek/resume/attachment/parser/upload` | 简历附件解析 |
| `/wapi/zppassport/login/phone` `/phoneV2` `/phoneV3` `/phoneByWy` | 手机验证码登录 |
| `/wapi/zpCommon/actionLog/previewSuccess` `previewFail` | 行为埋点 |
| `/wapi/zppassport/get/zpToken*` | token（robots 明示禁止） |

## 7. 未登录抓取的可行路径评估

| 路线 | 可行性 | 说明 |
|---|---|---|
| 直连抓 `job_detail` / `gongsi` / 类目页 | **当前不可行** | 出口 IP 已被标记，全部 302 到 security.html；换干净 IP 后可恢复（这些页本质是 SEO 落地页，正常服务端渲染） |
| 抓首页分类树 | **可行（已验证）** | 833 职位码 + 26 城市码，可离线构造全量类目 URL |
| 抓 SPA `/web/geek/job` | 不可行 | 空壳 + wapi 要登录态 |
| `wapi/zpgeek/search/joblist.json` 直连 | 不可行 | `code:37`，缺 `__zp_stoken__` |
| **Firecrawl `firecrawl_search` 的 SERP 摘要** | **可行** | 搜索结果 snippet 已含「岗位名 / 薪资 / 城市 / 经验 / 学历 / 福利」，无需进站；Firecrawl 云端抓详情页同样被 302 |
| Google/Bing 已索引的 `job_detail` 快照 | 视缓存策略 | 索引量大，但时效性差 |

## 8. 结论

1. 未登录的 BOSS 只有**首页**真正公开，其余内容页在风控命中后一律 302 到 `security.html`。
2. 站点的「结构」是可枚举的：**城市码 × 职位码 = 类目矩阵**，配合 `/job_detail/<encryptJobId>.html` 与 `/gongsi/<companyId>.html` 两种内容页。
3. 真正的数据入口只有两条：**登录态 + `__zp_stoken__`** 走 wapi，或**搜索引擎索引/SERP 摘要**。
4. 当前出口 IP 处于风控态，任何"进站抓取"的路子在冷却前都不会成功；先验证 IP 是否恢复（请求 `/job_detail` 看是否还 302）再谈方案。