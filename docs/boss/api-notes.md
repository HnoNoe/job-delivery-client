```markdown
# BOSS 接口与字段口径（实测）

> 全部结论来自 2026-11-26 / 27 的实机抓包（登录态 + 真实浏览器）
> 仅记录"页面自己会发的请求"，不含任何构造式调用

## 1. 端点清单

| 端点 | 用途 | 说明 |
|---|---|---|
| `/wapi/zpgeek/search/joblist.json` | 职位列表 | `zpData.jobList[]`，15 条/页，`totalCount` 上限 300 |
| `/wapi/zpgeek/job/detail.json` | 职位详情 | **仅 SPA 详情页会请求**；SEO 详情页（`/job_detail/xxx.html`）不请求，改读 DOM |
| `/wapi/zprelation/friend/getGeekFriendList.json` | 会话列表（求职者） | `zpData.result[]`，含 `lastMsg`/`lastTS`/`encryptUid` |
| `/wapi/zprelation/friend/geekFilterByLabel` | 会话联系人详情 | `friendList[]`，含 `name/brandName/jobName/bossTitle/updateTime` |
| `/wapi/zpchat/group/groupInfoList` | **群聊列表，不是会话** | 曾被误判为会话列表，返回 `[]` 不代表没有会话 |
| `/wapi/zpchat/config/ws` | WebSocket 集群地址 | `["ws.zhipin.com","ws6...","ws2..."]`，完整消息历史需走这里 |
| `/wapi/zpuser/wap/getUserInfo.json` | 当前账号 | `userId/name/identity/isHunter` |
| `/wapi/zpCommon/data/city.json` | 城市字典 | 3260 个「城市名 → 9 位城市码」，**未登录也可取** |

## 2. 列表字段（joblist → 统一中文列）

```text
jobName        → 岗位名称        salaryDesc     → 薪资
brandName      → 单位名称        cityName       → 城市
areaDistrict   → 区域            businessDistrict → 商圈
jobExperience  → 经验            jobDegree      → 学历
brandIndustry  → 行业            brandScaleName → 公司规模
brandStageName → 融资阶段        bossName       → HR
bossTitle      → HR职位          skills[]       → 技能（逗号连接）
encryptJobId   → 岗位链接 /job_detail/<id>.html
```

## 3. 详情字段（job/detail.json → 投递五布尔）

| 字段 | 含义 |
|---|---|
| `atsOnlineApplyInfo.alreadyApply` | 是否已投递 |
| `oneKeyResumeInfo.canSendResume` | 是否可一键发附件简历 |
| `oneKeyResumeInfo.canSendPhone` / `canSendWechat` | 是否可发手机 / 微信 |
| `relationInfo.beFriend` | 是否已开聊 |
| `relationInfo.interestJob` | 是否已"感兴趣" |
| `jobInfo.invalidStatus` | 职位是否失效 |

注意：BOSS **没有** `entryType/entryAddr` 这类字段，入口只能靠上面布尔值 + 页面按钮推断。

## 4. 页面 DOM 判据（SEO 详情页不请求 detail 接口时用）

投递入口（`boss_api.ENTRY_STATE_JS`）：

```javascript
var b = document.querySelector('.btn-startchat');
label = b.innerText.trim();          // "立即沟通" / "继续沟通"
hasResume = body.includes('投递简历') || body.includes('上传附件简历');
hasSent   = body.includes('已投递');
```

登录态（`boss_api.LOGIN_STATE_JS`）：

```javascript
var txt = document.querySelector('.user-nav').innerText;
loggedIn = txt.includes('消息') && !txt.includes('登录/注册');   // 已登录顶栏有「消息 / 简历 / 用户名」
```

## 5. 风控特征

```text
页面：/web/passport/zp/security.html?seed=...&name=...&ts=...&callbackUrl=...&code=36|37
接口：{"code":37,"message":"您的环境存在异常."}
内容页未登录命中时：/job_detail/* → 302 → security.html
```

`code=36` 账号异常（可能升级图形验证码）；`code=37` 环境异常（IP / 设备指纹被标记）。

## 6. robots 与合规

```text
Disallow: /*?query=*      ← 关键词搜索页（当前 capture 使用的通道）
Disallow: /*?ka=*         Disallow: *?city=*    Disallow: *?salary=*
Disallow: /web/boss/*     Disallow: /wapi/zppassport/get/zpToken*
（未禁止）/job_detail/<id>.html      除 l* 前缀
（未禁止）/c<9位城市码>-p<6位职位码>/  类目页，SSR 直出岗位
```

**合规建议**：类目页 `/c100010000-p100109/` 是 SSR 通道，实测直接返回 36 条岗位的
名称/薪资/公司/区域，且不在 robots 禁止范围内，应作为主通道；关键词搜索页仅作补充。
