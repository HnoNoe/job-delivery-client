# 岗位抓取 + 投递 端到端验证报告

> 时间：2026-11-26 18:25–18:35
> 账号：徐汪杰（userId 788550731，identity=0 求职者）
> 方式：CDP 只开 Network 域旁听 + `Input.dispatchMouseEvent` 可信点击；无 headless、无 webdriver 标记、无人工介入

## 1. 抓取（通过）

```
CRAWL code=0  n=15  totalCount=300        ← 北京 / 关键词 Python
候选（示例）：
  15-30K·15薪 | Python开发（接受无经验） | 外企德科数字 | 6c713866432169a00nV80t69E1pZ
  50-1000元/天 | python量化研究员远程   | 北京五十步电子商务 | 41d82393cf0ca26d0nV-2dS1EltT
  15-25K·14薪 | 后端开发+算法工程师     | 某大型互联网公司 | edc8f3854bfcc17a0n163du6FlBW
```

详情接口 `/wapi/zpgeek/job/detail.json` → `code=0`：

```json
{"atsOnlineApplyInfo": {"inviteType":0,"alreadyApply":false},
 "oneKeyResumeInfo":  {"canSendResume":false,"canSendPhone":false,"canSendWechat":false},
 "relationInfo":      {"interestJob":false,"beFriend":false}}
```

→ 判定：可投递，走「立即沟通」（半自动通道）。

## 2. 投递（通过）

| 步骤 | 证据 |
|---|---|
| 定位按钮 | `.btn-startchat` rect 中心 (561, 222)，`elementFromPoint` 校验命中 |
| 可信点击 | `Input.dispatchMouseEvent` mousePressed/mouseReleased → `isTrusted=true` |
| 按钮状态变化 | 点击前「立即沟通」→ 点击后「**继续沟通**」 |
| 会话创建 | 聊天页 `getGeekFriendList.json` 出现新会话：**刘雨瑶 / 外企德科数字 / Python开发（接受无经验）/ 18:32** |
| 首条消息 | 该会话 `lastMsg` = 「您好，我是四川农业大学本科生，我积极主动，乐于学习，希望能得到您的回复。」 |

**注意**：这条招呼语不是脚本写的（我的填字步骤失败，页面当时没有 textarea/POST 内容）。它应该是账号里配置的**默认招呼语**，由 BOSS 在点「立即沟通」时自动发出。需要你确认。

## 3. 消息/会话抓取（通过，并修正了此前的错误结论）

**`groupInfoList` 不是会话列表**（那是群聊），真实会话接口是：

| 端点 | 内容 |
|---|---|
| `/wapi/zprelation/friend/getGeekFriendList.json` | `code=0`，9 条会话，含 `lastMsg`/`lastTS`/`chatStatus`/`encryptUid` |
| `/wapi/zprelation/friend/geekFilterByLabel` | `code=0`，9 条联系人详情：`name/brandName/jobName/jobCity/bossTitle/updateTime` |

实测 9 条真实会话（`_research/sessions.jsonl`）：

| 时间 | HR | 公司 | 岗位 | 最后一条消息（截断） |
|---|---|---|---|---|
| 11-26 18:32 | 刘雨瑶 | 外企德科数字 | Python开发（接受无经验） | 您好，我是四川农业大学本科生… |
| 11-23 11:22 | 王女士 | 途游游戏 | Python后端开发（北京）-2027… | 感谢您的关注，暂时不适合该岗位… |
| 11-21 20:27 | 许女士 | 任性娱乐 | 服装穿板模特（接小白） | 你好，有兴趣做模特吗… |
| 11-20 18:28 | 王瑞 | 江苏环益童心信息科技 | 活动策划 | 同学有兴趣了解一下吗… |
| 11-19 12:27 | 刘女士 | 云赛思创 | python后端开发 | 您好，我是徐汪杰（四川农业大学…） |
| 11-19 12:27 | 陶女士 | 易博互通企服科技 | 北智教育-Python后端开发 | 同上系列招呼语 |
| 11-19 12:26 | 曹雅琴 | 中科院信工所 | 后端开发工程师(python/AI) | 同上系列招呼语 |
| 11-12 10:21 | 祝女士 | 武汉领格卓越教育科技 | 销售运营实习生 | 你好，看了你的在线简历… |
| 11-09 20:29 | 陆女士 | 卡尔动力 | 27届校招-后端开发（Python/C++） | [hi] 你好啊，可以聊一聊~ |

## 4. 未完成的部分（如实说明）

**单条会话的完整消息历史未抓到。** 在聊天页按文本定位会话项并点击（坐标 511,206），页面无反应、也没有新的消息接口被触发。可能原因：列表项事件绑定在外层容器、或需要滚动/双击。
→ 下一步要么换更精确的选择器（`.friend-list-item` 容器级 rect），要么抓 WebSocket（`zpchat/config/ws` 给出 ws.zhipin.com 集群）拿增量消息。

## 5. 对方案可行性的结论

| 能力 | 结论 |
|---|---|
| 无人工抓岗位 | ✅ 可用（15 条/页，300/关键词） |
| 补详情/投递判定 | ✅ 可用（ats/oneKey/relation 五布尔） |
| 无人工投递 | ✅ 可用（可信点击 + 自动招呼语 + 会话落库） |
| 会话列表 + 消息预览 | ✅ 可用（`zprelation/friend/*`） |
| 完整消息历史 | ⏳ 待解决（选择器或 WS） |
| 风控 | 本轮全程无 `security.html`，无验证码 |