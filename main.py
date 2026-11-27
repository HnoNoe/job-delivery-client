"""CLI 入口 —— 裁剪后的最小系统：只保留 登录 / 检索岗位 / 投递。

用法：
  python main.py login <platform>            用你自己的浏览器打开登录页（手动登录）
  python main.py grab <platform>             从本机浏览器读出登录态存盘（登录完成后执行；
                                             Edge/Chrome 新版加密需以管理员身份运行本程序）
  python main.py search <platform> <关键词> [--pages N]   检索并入岗位库
  python main.py maketasks                   把岗位库里的在架岗位建成投递任务（去重）
  python main.py deliver [--limit N]         批量投递待投递任务（安全模式默认只准备材料）
  python main.py status                      看登录态/岗位/任务统计
  python main.py browser open <平台>         启动 CDP 浏览器（默认隐藏窗口；首次需登录一次）
  python main.py browser status|close        查看/关闭该浏览器
  python main.py capture <平台> <关键词> [--city C] [--pages N]
                                             CDP 旁听采集并入岗位库（结束自动关浏览器）
  python main.py apply [平台] [--limit N] [--yes]   CDP 自动投递（默认演练，--yes 才真点）
"""
import argparse
import json
import sys


def _check_login(br, boss_api):
    """读页面 DOM 判断登录态 -> (logged_in, name, url)。不发额外请求。"""
    state = boss_api.parse_login_state(br.evaluate(boss_api.LOGIN_STATE_JS))
    return bool(state.get("loggedIn")), state.get("name") or "", state.get("url") or ""


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="jobdelivery", description="求职批量投递（检索+投递最小系统）")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("login", help="用你自己的浏览器打开平台登录页")
    lg.add_argument("platform")

    gr = sub.add_parser("grab", help="从本机浏览器读取登录态存盘")
    gr.add_argument("platform")

    se = sub.add_parser("search", help="检索岗位并入库")
    se.add_argument("platform")
    se.add_argument("keyword")
    se.add_argument("--pages", type=int, default=2)
    se.add_argument("--city", default="")

    sub.add_parser("maketasks", help="岗位库 → 投递任务（去重）")

    bt = sub.add_parser("deliver", help="批量投递待投递任务")
    bt.add_argument("--limit", type=int, default=0)
    bt.add_argument("--all", action="store_true", help="投全部待投递（仍受每日上限约束）")

    sub.add_parser("status", help="登录态/岗位/任务统计")

    bv = sub.add_parser("browser", help="管理 CDP 浏览器（默认隐藏窗口）")
    bv.add_argument("action", choices=["open", "status", "close"])
    bv.add_argument("platform", nargs="?", default="boss")
    bv.add_argument("--port", type=int, default=0)
    bv.add_argument("--profile", default="", help="浏览器 profile 目录（默认落在运行目录 browser/<平台>/profile）")
    bv.add_argument("--chrome", default="", help="Chrome/Edge 可执行文件路径")
    bv.add_argument("--show", action="store_true", help="显示窗口（默认最小化隐藏）")

    cp = sub.add_parser("capture", help="CDP 旁听采集岗位并入库（结束自动关闭浏览器）")
    cp.add_argument("platform")
    cp.add_argument("keyword")
    cp.add_argument("--city", default="")
    cp.add_argument("--pages", type=int, default=1)
    cp.add_argument("--port", type=int, default=0)
    cp.add_argument("--profile", default="")
    cp.add_argument("--chrome", default="")
    cp.add_argument("--show", action="store_true", help="显示窗口（默认最小化隐藏）")
    cp.add_argument("--keep-open", action="store_true", help="采集结束保留浏览器")

    lc = sub.add_parser("login-check", help="检查 CDP 浏览器登录态（失效退出码 1；可轮询）")
    lc.add_argument("platform", nargs="?", default="boss")
    lc.add_argument("--port", type=int, default=0)
    lc.add_argument("--profile", default="")
    lc.add_argument("--chrome", default="")
    lc.add_argument("--show", action="store_true", help="显示窗口（默认最小化隐藏）")
    lc.add_argument("--interval", type=int, default=0, help="轮询间隔秒数（0=只查一次）")
    lc.add_argument("--times", type=int, default=0, help="轮询次数（0=一直轮询）")

    ap = sub.add_parser("apply", help="CDP 自动投递：读详情→判定入口→点「立即沟通」（默认只演练）")
    ap.add_argument("platform", nargs="?", default="boss")
    ap.add_argument("--job", default="", help="岗位链接或 encryptJobId；留空取岗位库里最新一条")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--profile", default="")
    ap.add_argument("--chrome", default="")
    ap.add_argument("--show", action="store_true", help="显示窗口（默认最小化隐藏）")
    ap.add_argument("--keep-open", action="store_true", help="结束保留浏览器")
    ap.add_argument("--yes", action="store_true", help="真正点击投递（不加只演练）")

    a = p.parse_args(argv)

    if a.cmd == "login":
        import grab_login
        ok, msg = grab_login.open_in_user_browser(a.platform)
        print(("✅ " if ok else "❌ ") + msg)
        return 0 if ok else 1

    if a.cmd == "grab":
        from urllib.parse import urlparse
        import grab_login
        import platforms as plats
        import session
        host = urlparse((plats.get(a.platform) or {}).get("login_url", "")).hostname or ""
        domain = ".".join(host.split(".")[-2:]) if host else ""
        cookies, err = grab_login.grab_cookies(domain)
        if not cookies:
            hint = "" if grab_login.is_admin() else \
                "\n提示：Edge/Chrome 新版加密需要管理员权限——请右键→以管理员身份运行本程序再执行 grab。"
            print("❌ 读取失败：%s%s" % (err, hint))
            return 1
        n = session.save_cookies(a.platform, cookies)
        print("✅ 已保存 %d 个 cookie（平台：%s）" % (n, a.platform))
        return 0

    if a.cmd == "search":
        import jobstore
        import loop
        import session
        if not session.can_search(a.platform):
            print("❌ %s 没有可用登录态，请先 login + grab。" % a.platform)
            return 1
        jobs, logs = loop.search_logged_in_platforms([a.platform], a.keyword,
                                                     city=a.city, pages=a.pages)
        for k, msg in logs:
            print("  [%s] %s" % (k, msg))
        n = jobstore.store_jobs(jobs, user_id=1)
        print("✅ 入库 %d 个岗位（检索到 %d 条）。" % (n, len(jobs)))
        print("下一步：python main.py maketasks")
        return 0

    if a.cmd == "maketasks":
        import db
        import delivery
        created = 0
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT job_id, fields FROM jobs WHERE active=1 ORDER BY job_id").fetchall()
            for r in rows:
                f = json.loads(r["fields"])
                exists = conn.execute(
                    "SELECT 1 FROM delivery_tasks WHERE job_id=? AND user_id=1",
                    (r["job_id"],)).fetchone()
                if exists:
                    continue
                entry_type, entry_addr = delivery.classify_entry(
                    f.get("投递入口类型", ""), f.get("投递入口地址", "")) \
                    if False else (f.get("投递入口类型", ""), f.get("投递入口地址", ""))
                conn.execute(
                    "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, job_link,"
                    " entry_type, entry_addr, status) VALUES (?,?,?,?,?,?,?,'待投递')",
                    (r["job_id"], 1, f.get("岗位名称", ""), f.get("单位名称", ""),
                     f.get("岗位链接", ""), entry_type, entry_addr))
                created += 1
            conn.commit()
        print("✅ 新建 %d 个投递任务（已存在的自动跳过）。" % created)
        return 0

    if a.cmd == "deliver":
        import delivery
        res = delivery.deliver_batch(limit=a.limit or None, all_pending=a.all)
        print(json.dumps({k: v for k, v in res.items() if k != "明细"},
                         ensure_ascii=False, indent=2))
        for task_id, ok, msg in res.get("明细", []):
            print("  任务%s：%s %s" % (task_id, "✅" if ok else "❌", msg))
        return 0

    if a.cmd == "browser":
        import cdp_browser
        import platforms as plats
        port = a.port or cdp_browser.DEFAULT_PORT
        br = cdp_browser.CdpBrowser(a.platform, port=port, profile_dir=a.profile or None,
                                    chrome_exe=a.chrome or None, hidden=not a.show,
                                    keep_open=True)
        if a.action == "status":
            print(("✅ 浏览器在运行（端口 %d）" % port) if br.running()
                  else ("⭕ 浏览器未运行（端口 %d）" % port))
            print("   profile：%s" % br.profile_dir)
            if br.running():
                ok, msg = br.attach()
                if ok:
                    ok2, who, url2 = _check_login(br, __import__("boss_api"))
                    print("   登录态：%s" % (("✅ 已登录 " + (who or "")) if ok2
                                          else "❌ 未登录（%s）" % (url2 or "-")))
                    br.close()
            return 0
        if a.action == "open":
            ok, msg = br.ensure_running()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            ok, msg = br.attach()
            print(("✅ " if ok else "❌ ") + msg)
            print("   profile：%s" % br.profile_dir)
            login_url = (plats.get(a.platform) or {}).get("login_url", "")
            if login_url:
                br.goto(login_url, settle=5.0)
                print("   已打开登录页：%s" % login_url)
            cdp_browser.remember_profile(a.platform, br.profile_dir)
            print("   已记住该 profile，后续 capture / apply / login-check 默认用它。")
            br.show()
            print("   请在弹出的窗口里扫码/短信登录；登录完成后可跑 login-check 确认。")
            return 0 if ok else 1
        ok, msg = br.close()
        print(("✅ " if ok else "❌ ") + msg)
        return 0

    if a.cmd == "capture":
        import time as _time
        from urllib.parse import quote
        import boss_api
        import cdp_browser
        import jobstore
        import platforms as plats
        recipe = (plats.get(a.platform) or {}).get("capture")
        if not recipe:
            print("❌ 平台 %s 没有 CDP 采集配方（在 platforms.py 补 capture 字段）。" % a.platform)
            return 1
        port = a.port or cdp_browser.DEFAULT_PORT
        br = cdp_browser.CdpBrowser(a.platform, port=port, profile_dir=a.profile or None,
                                    chrome_exe=a.chrome or None, hidden=not a.show,
                                    keep_open=a.keep_open)
        collected = []
        try:
            ok, msg = br.ensure_running()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            ok, msg = br.attach()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            br.goto("https://www.zhipin.com/web/geek/jobs", settle=6.0)
            logged, name, _url = _check_login(br, boss_api)
            if not logged:
                print("❌ 未登录：该 profile 登录态已失效，请先 python main.py browser open %s 重新登录。"
                      % a.platform)
                return 1
            print("  登录账号：%s" % (name or "(未知)"))
            pages = max(1, a.pages)
            risk_hit = False
            for page in range(1, pages + 1):
                url = recipe["search_url"].format(keyword=quote(a.keyword),
                                                  city=a.city or "101010100")
                if page > 1:
                    url += "&page=%d" % page
                responses = br.goto(url, match=[recipe["joblist_kw"]],
                                    settle=12.0,
                                    fresh=bool(recipe.get("needs_full_reload", True)))
                risk_msg = boss_api.detect_risk(url=br.evaluate("location.href"))
                if not risk_msg:
                    for item in responses:
                        risk_msg = boss_api.detect_risk(payload=item["body"]) or risk_msg
                if risk_msg:
                    print("🛑 命中风控，已立即停止：%s" % risk_msg)
                    print("   %s" % boss_api.RISK_ADVICE)
                    risk_hit = True
                    break
                page_jobs = []
                for item in responses:
                    page_jobs.extend(boss_api.parse_joblist(item["body"]))
                print("  第 %d 页：抓到 %d 条" % (page, len(page_jobs)))
                collected.extend(page_jobs)
                if not page_jobs:
                    break
                if page < pages:
                    _time.sleep(recipe.get("page_interval", 12))
        finally:
            ok, msg = br.close()
            print(("✅ " if ok else "❌ ") + msg)
        if risk_hit:
            if collected:
                n = jobstore.store_jobs(collected, user_id=1)
                print("⚠️ 因风控提前结束，已入库已抓到的 %d 个岗位。" % n)
            return 2
        if not collected:
            print("❌ 没抓到岗位：确认该浏览器已登录 %s（先跑 python main.py browser open %s）。"
                  % (a.platform, a.platform))
            return 1
        n = jobstore.store_jobs(collected, user_id=1)
        print("✅ 入库 %d 个岗位（本次抓到 %d 条）。" % (n, len(collected)))
        return 0

    if a.cmd == "login-check":
        import time as _time
        import boss_api
        import cdp_browser
        port = a.port or cdp_browser.DEFAULT_PORT
        br = cdp_browser.CdpBrowser(a.platform, port=port, profile_dir=a.profile or None,
                                    chrome_exe=a.chrome or None, hidden=not a.show,
                                    keep_open=bool(a.interval))
        rounds = 0
        try:
            ok, msg = br.ensure_running()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            ok, msg = br.attach()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            while True:
                rounds += 1
                br.goto("https://www.zhipin.com/web/geek/jobs", settle=6.0)
                logged, name, url = _check_login(br, boss_api)
                if logged:
                    print("[%d] ✅ 登录态正常：%s" % (rounds, name or "(未知)"))
                else:
                    print("[%d] ❌ 登录态已失效（页面：%s）" % (rounds, url or "-"))
                    print("    处理：python main.py browser open %s 后在该窗口里重新登录。" % a.platform)
                if not a.interval:
                    return 0 if logged else 1
                if a.times and rounds >= a.times:
                    return 0 if logged else 1
                _time.sleep(max(15, a.interval))
        finally:
            ok, msg = br.close()
            print(("✅ " if ok else "❌ ") + msg)

    if a.cmd == "apply":
        import time as _time
        import boss_api
        import cdp_browser
        import db
        import platforms as plats
        recipe = (plats.get(a.platform) or {}).get("capture")
        if not recipe:
            print("❌ 平台 %s 没有 CDP 采集配方。" % a.platform)
            return 1
        targets = []
        if a.job:
            encrypt_id = a.job.rstrip("/").split("/")[-1].replace(".html", "")
            targets.append({"job_id": encrypt_id, "岗位名称": "", "单位名称": ""})
        else:
            with db.get_conn() as conn:
                rows = conn.execute(
                    "SELECT job_id, fields FROM jobs WHERE active=1 ORDER BY job_id DESC LIMIT ?",
                    (max(1, a.limit),)).fetchall()
            for row in rows:
                fields = json.loads(row["fields"] or "{}")
                link = fields.get("岗位链接", "")
                encrypt_id = link.rstrip("/").split("/")[-1].replace(".html", "")
                if not encrypt_id:
                    continue
                targets.append({"job_id": encrypt_id,
                                "岗位名称": fields.get("岗位名称", ""),
                                "单位名称": fields.get("单位名称", "")})
        if not targets:
            print("❌ 岗位库没有在架岗位，先跑 capture。")
            return 1
        port = a.port or cdp_browser.DEFAULT_PORT
        br = cdp_browser.CdpBrowser(a.platform, port=port, profile_dir=a.profile or None,
                                    chrome_exe=a.chrome or None, hidden=not a.show,
                                    keep_open=a.keep_open)
        done = 0
        try:
            ok, msg = br.ensure_running()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            ok, msg = br.attach()
            print(("✅ " if ok else "❌ ") + msg)
            if not ok:
                return 1
            for item in targets:
                url = recipe["detail_url"].format(job_id=item["job_id"])
                br.goto(url, settle=8.0)
                risk_msg = boss_api.detect_risk(url=br.evaluate("location.href"))
                if risk_msg:
                    print("🛑 命中风控，已立即停止：%s" % risk_msg)
                    print("   %s" % boss_api.RISK_ADVICE)
                    return 2
                logged, who, cur_url = _check_login(br, boss_api)
                if not logged:
                    print("❌ 未登录：该 profile 登录态已失效（页面：%s）。" % (cur_url or "-"))
                    print("    处理：python main.py browser open %s 后重新登录。" % a.platform)
                    return 1
                state = boss_api.read_entry_state(br.evaluate(boss_api.ENTRY_STATE_JS))
                entry_type, why = boss_api.decide_entry_state(state)
                print("  岗位 %s｜%s｜%s" % (item["job_id"],
                                           item.get("岗位名称") or "-",
                                           item.get("单位名称") or "-"))
                print("    页面按钮：%s" % ((state.get("label") or "（未找到）")))
                print("    投递入口：%s（%s）" % (entry_type, why))
                if not a.yes:
                    print("    演练模式：未点击（加 --yes 才真正投递）")
                    continue
                if entry_type in ("未知",) or "跳过" in why:
                    print("    跳过该岗位")
                    continue
                if not a.show:
                    br.show()
                    _time.sleep(1.5)
                base_label = state.get("label") or ""
                clicked = False
                for attempt, selector in enumerate((".btn-startchat", ".btn-startchat-wrap")):
                    br.bring_to_front()
                    _time.sleep(0.8)
                    ok2, msg2 = br.click_selector(selector, retries=1)
                    print("    " + ("✅ " if ok2 else "❌ ") + msg2)
                    if not ok2:
                        continue
                    _time.sleep(4)
                    after = boss_api.read_entry_state(br.evaluate(boss_api.ENTRY_STATE_JS))
                    label_after = after.get("label") or ""
                    print("    点击后按钮：%s" % (label_after or "-"))
                    if label_after and label_after != base_label:
                        clicked = True
                        break
                    print("    [!] 第 %d 次点击未生效%s" % (attempt + 1, "，改用外层容器重试" if attempt == 0 else ""))
                    br.press_escape()
                    _time.sleep(1.0)
                if clicked:
                    done += 1
                if not a.show:
                    br.hide()
                _time.sleep(3)
        finally:
            ok, msg = br.close()
            print(("✅ " if ok else "❌ ") + msg)
        if done:
            print("✅ 完成投递 %d 个岗位。" % done)
        else:
            print("⭕ 本次没有真正投递（演练、跳过或点击未生效）。")
        return 0

    if a.cmd == "status":
        import login_status
        import session
        import db
        for st in login_status.check_all(online=False):
            print("  登录态 %-8s %s %s" % (st["key"], st["state"], st.get("detail", "")))
        with db.get_conn() as conn:
            nj = conn.execute("SELECT COUNT(*) c FROM jobs WHERE active=1").fetchone()["c"]
            nt = conn.execute("SELECT COUNT(*) c FROM delivery_tasks").fetchone()["c"]
            np_ = conn.execute(
                "SELECT COUNT(*) c FROM delivery_tasks WHERE status='待投递'").fetchone()["c"]
            nd = conn.execute(
                "SELECT COUNT(*) c FROM delivery_tasks WHERE status='已投递'").fetchone()["c"]
        print("  岗位库在架 %d；任务 %d（待投递 %d / 已投递 %d）" % (nj, nt, np_, nd))
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
