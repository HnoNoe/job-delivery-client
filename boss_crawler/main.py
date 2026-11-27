# -*- coding: utf-8 -*-
"""
main.py —— 程序入口
====================
在 PyCharm 里右键 Run 这个文件即可；也可以在终端里运行：

    python main.py check                     环境自检（装没装依赖、找不找得到浏览器）
    python main.py login                     打开登录页（首次必须做一次，登录态存在本文件夹里）
    python main.py search -k Python -c 北京 -p 1     抓岗位（默认 6 关键词 × 8 城市 × 1 页）
    python main.py detail -n 3               给前 3 条岗位补详情（投递入口判定）
    python main.py chat                      抓"沟通过"的 HR 会话列表
    python main.py search -k Python --show    想看着它跑就加 --show（默认隐藏窗口）

说明：
    · 浏览器由本程序拉起，默认隐藏窗口（最小化），任务结束自动关闭
    · 不加 --headless：BOSS 会直接判环境异常
    · 只旁听页面自己发出的请求，不构造业务接口、不注入脚本
"""

import argparse
import sys
import time
from pathlib import Path

import browser as br_mod
import config
import exporter
import parser
import risk
from utils import fix_console_encoding, get_logger, open_path, parse_list, sleep_between

ROOT = Path(__file__).resolve().parent


def build_parser():
    p = argparse.ArgumentParser(
        description="BOSS直聘岗位采集工具（CDP 旁听版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python main.py search -k Python,Java -c 北京,上海 -p 2",
    )
    p.add_argument("action", nargs="?", default="search",
                   choices=["check", "login", "search", "detail", "chat"],
                   help="要执行的动作（默认 search）")
    p.add_argument("-k", "--keywords", default=",".join(config.DEFAULT_KEYWORDS),
                   help="搜索关键词，多个用英文逗号分隔（默认：%(default)s）")
    p.add_argument("-c", "--cities", default=",".join(config.DEFAULT_CITIES),
                   help="城市，多个用英文逗号分隔（默认：%(default)s）")
    p.add_argument("-p", "--pages", type=int, default=1, help="每个组合翻几页（默认 1，最多 %d）" % config.MAX_PAGES)
    p.add_argument("-m", "--max", type=int, default=300, help="最多抓多少条（去重后，默认 300）")
    p.add_argument("-n", "--top", type=int, default=3, help="detail 动作：补前几条岗位的详情（默认 3）")
    p.add_argument("--port", type=int, default=config.DEFAULT_PORT, help="调试端口（默认 %(default)s）")
    p.add_argument("--profile", default="", help="浏览器 profile 目录（默认本文件夹下 browser_data）")
    p.add_argument("--chrome", default="", help="Chrome/Edge 可执行文件路径")
    p.add_argument("--show", action="store_true", help="显示浏览器窗口（默认隐藏）")
    p.add_argument("--keep-open", action="store_true", help="结束后保留浏览器")
    p.add_argument("--open", action="store_true", help="结束后打开 output 文件夹")
    return p


def banner(log):
    log.info("=" * 62)
    log.info("  BOSS直聘 岗位采集工具（CDP 旁听，真实浏览器）")
    log.info("  仅供个人学习与求职分析使用，请控制频率、遵守网站规则")
    log.info("=" * 62)


def make_browser(args, keep_open=None):
    return br_mod.Browser(
        port=args.port,
        profile_dir=args.profile or (ROOT / config.BROWSER_PROFILE),
        chrome_exe=args.chrome or None,
        hidden=not args.show,
        keep_open=args.keep_open if keep_open is None else keep_open,
    )


def ensure_ready(br, log):
    """启动浏览器 + 附着页面 + 检查登录态。返回 bool。"""
    ok, msg = br.ensure_running()
    log.info(("✅ " if ok else "❌ ") + msg)
    if not ok:
        return False
    ok, msg = br.attach()
    log.info(("✅ " if ok else "❌ ") + msg)
    if not ok:
        return False
    state = parser.read_state(br.evaluate(parser.LOGIN_STATE_JS))
    if not state.get("loggedIn"):
        log.error("❌ 没登录：先跑 python main.py login，在弹出的窗口里扫码登录。")
        return False
    log.info("  登录账号：%s" % (state.get("name") or "(未知)"))
    return True


def do_check(args, log):
    import check_env
    return check_env.main()


def do_login(args, log):
    br = make_browser(args, keep_open=True)
    try:
        ok, msg = br.ensure_running()
        log.info(("✅ " if ok else "❌ ") + msg)
        if not ok:
            return 1
        ok, msg = br.attach()
        log.info(("✅ " if ok else "❌ ") + msg)
        if not ok:
            return 1
        br.goto(config.LOGIN_URL, settle=5.0)
        br.show()
        log.info("  请在打开的窗口里扫码/短信登录，然后关掉窗口或按回车继续。")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        state = parser.read_state(br.evaluate(parser.LOGIN_STATE_JS))
        if state.get("loggedIn"):
            log.info("✅ 登录成功：%s" % (state.get("name") or "(未知)"))
            return 0
        log.error("❌ 仍是未登录状态，请重新运行 python main.py login")
        return 1
    finally:
        br.close()


def do_search(args, log):
    keywords = parse_list(args.keywords)
    cities = parse_list(args.cities)
    unknown = [c for c in cities if c not in config.CITY_CODES]
    if unknown:
        log.error("不认识的城市：%s" % "、".join(unknown))
        log.error("可用城市：%s" % "、".join(config.CITY_CODES))
        return 1
    pages = max(1, min(int(args.pages), config.MAX_PAGES))
    log.info("  关键词：%s" % "、".join(keywords))
    log.info("  城市：%s（%d 页/组合）" % ("、".join(cities), pages))

    br = make_browser(args)
    collected, seen = [], set()
    stopped = ""
    try:
        if not ensure_ready(br, log):
            return 1
        try:
            for keyword in keywords:
                for city in cities:
                    for page in range(1, pages + 1):
                        url = config.SEARCH_URL.format(city=config.CITY_CODES[city],
                                                       keyword=keyword)
                        if page > 1:
                            url += "&page=%d" % page
                        responses = br.goto(url, match=["zpgeek/search/joblist.json"], settle=12.0)
                        # 熔断：先看页面有没有被跳到安全验证页
                        risk.check_url(br.evaluate("location.href"))
                        rows = []
                        for resp in responses:
                            risk.check_payload(resp["body"])
                            rows.extend(parser.parse_joblist(resp["body"]))
                        if not rows:
                            # 没有数据也没被拦：可能是登录态失效或本页无结果，视为软失败
                            log.warning("  [%s/%s 第%d页] 没有拿到岗位数据，停止本轮" % (keyword, city, page))
                            raise StopIteration
                        fresh = 0
                        for item in rows:
                            key = item.get("岗位链接") or item.get("岗位名称")
                            if not key or key in seen:
                                continue
                            seen.add(key)
                            item["关键词"] = keyword
                            item["采集时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
                            collected.append(item)
                            fresh += 1
                        log.info("  [%s/%s 第%d页] 抓到 %d 条，新增 %d 条，累计 %d 条"
                                 % (keyword, city, page, len(rows), fresh, len(collected)))
                        if len(collected) >= args.max:
                            raise StopIteration
                        sleep_between(config.MIN_DELAY, config.MAX_DELAY)
        except risk.RiskControlError as exc:
            stopped = str(exc)
            log.error("🛑 命中风控，已立即停止：%s" % exc)
            log.error("   %s" % risk.advice())
        except StopIteration:
            pass
    finally:
        br.close()

    if stopped:
        if collected:
            files = exporter.export_all(collected)
            log.warning("⚠️ 因风控提前结束，已保存已抓到的 %d 条：" % len(collected))
            for name, path in files.items():
                log.warning("   %-5s -> %s" % (name, Path(path).relative_to(ROOT)))
        return 2
    if not collected:
        log.error("❌ 一条都没抓到：确认已登录、关键词/城市没写错。")
        return 1
    files = exporter.export_all(collected)
    log.info("✅ 采集完成，共 %d 条（去重后）" % len(collected))
    for name, path in files.items():
        log.info("   %-5s -> %s" % (name, Path(path).relative_to(ROOT)))
    if args.open:
        open_path(ROOT / "output")
    return 0


def do_detail(args, log):
    records = exporter.load_raw()
    if not records:
        log.error("❌ 还没有原始数据，先跑 python main.py search")
        return 1
    targets = [r for r in records[:max(1, args.top)] if r.get("岗位链接")]
    if not targets:
        log.error("❌ 原始数据里没有可用的岗位链接")
        return 1
    br = make_browser(args)
    rows = []
    try:
        if not ensure_ready(br, log):
            return 1
        for item in targets:
            job_id = item["岗位链接"].rstrip("/").split("/")[-1].replace(".html", "")
            try:
                responses = br.goto(config.DETAIL_URL.format(job_id=job_id), settle=9.0)
                risk.check_url(br.evaluate("location.href"))
                detail = {}
                for resp in responses:
                    if "job/detail.json" in resp["url"]:
                        risk.check_payload(resp["body"])
                    detail = parser.parse_detail(resp["body"]) or detail
            except risk.RiskControlError as exc:
                log.error("🛑 命中风控，已立即停止：%s" % exc)
                log.error("   %s" % risk.advice())
                return 2
            state = parser.read_state(br.evaluate(parser.ENTRY_STATE_JS))
            entry_type, why = parser.decide_entry(detail, state)
            row = dict(item)
            row.update({"详情": detail, "页面按钮": state.get("label", ""),
                        "投递入口": entry_type, "入口说明": why})
            rows.append(row)
            log.info("  %s | %s | 入口=%s（%s）"
                     % (item.get("岗位名称", "")[:22], item.get("单位名称", "")[:14], entry_type, why))
            sleep_between(config.MIN_DELAY / 2, config.MAX_DELAY / 2)
    finally:
        br.close()
    path = exporter.save_raw(rows, "raw/岗位详情.jsonl")
    log.info("✅ 详情补完 %d 条 -> %s" % (len(rows), Path(path).relative_to(ROOT)))
    return 0


def do_chat(args, log):
    br = make_browser(args)
    rows = []
    try:
        if not ensure_ready(br, log):
            return 1
        try:
            responses = br.goto(config.CHAT_URL, match=["zprelation/friend/"], settle=14.0)
            risk.check_url(br.evaluate("location.href"))
            for resp in responses:
                risk.check_payload(resp["body"])
                rows = parser.parse_friend_list(resp["body"]) or rows
        except risk.RiskControlError as exc:
            log.error("🛑 命中风控，已立即停止：%s" % exc)
            log.error("   %s" % risk.advice())
            return 2
    finally:
        br.close()
    if not rows:
        log.error("❌ 没抓到会话：可能没有沟通过，或登录态失效。")
        return 1
    path = exporter.save_raw(rows, config.CHAT_JSONL)
    log.info("✅ 抓到 %d 个 HR 会话 -> %s" % (len(rows), Path(path).relative_to(ROOT)))
    for row in rows[:5]:
        log.info("   %s | %s | %s" % (row["HR"], row["单位名称"][:14], str(row["最后消息"])[:34]))
    return 0


def main(argv=None):
    fix_console_encoding()
    args = build_parser().parse_args(argv)
    log = get_logger(ROOT)
    banner(log)
    handlers = {"check": do_check, "login": do_login, "search": do_search,
                "detail": do_detail, "chat": do_chat}
    return handlers[args.action](args, log)


if __name__ == "__main__":
    sys.exit(main())
