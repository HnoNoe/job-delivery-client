"""智投链·本地桌面客户端。

账号注册登录（本地 PBKDF2）+ 简历字段编辑（与 8445 网页版同构）+
浏览器自动化三件套：抓取岗位 / 自动投递 / 任务追踪。无画像/匹配。
所有耗时操作跑在后台线程，日志实时进下方文本框。
"""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import auth
import config
import db
import jobstore
import login_status
import platforms
import resume_store
import schema
import session

log_queue = queue.Queue()


def log(msg):
    log_queue.put(str(msg))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("智投链 · 本地客户端")
        self.geometry("900x640")
        self.user = auth.current_user()
        self.exp_rows = []  # 简历页经历列表（dict）
        self._qr_win = None  # 扫码登录窗口（同时只允许一个）

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_account = ttk.Frame(nb); nb.add(self.tab_account, text="① 账号")
        self.tab_resume = ttk.Frame(nb);  nb.add(self.tab_resume, text="② 简历")
        self.tab_plogin = ttk.Frame(nb);  nb.add(self.tab_plogin, text="③ 平台登录")
        self.tab_search = ttk.Frame(nb);  nb.add(self.tab_search, text="④ 抓取岗位")
        self.tab_deliver = ttk.Frame(nb); nb.add(self.tab_deliver, text="⑤ 投递")
        self.tab_tasks = ttk.Frame(nb);   nb.add(self.tab_tasks, text="⑥ 任务追踪")

        self._build_account(); self._build_resume(); self._build_plogin()
        self._build_search(); self._build_deliver(); self._build_tasks()

        self.logbox = scrolledtext.ScrolledText(self, height=8, state="disabled")
        self.logbox.pack(fill="x", side="bottom")
        self.after(200, self._drain_log)
        self._refresh_user_state()

    # ---------- 日志 ----------
    def _drain_log(self):
        try:
            while True:
                line = log_queue.get_nowait()
                self.logbox.configure(state="normal")
                self.logbox.insert("end", line + "\n")
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._drain_log)

    def _run(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _refresh_user_state(self):
        self.user = auth.current_user()
        if self.user:
            self.lbl_user.config(text="当前账号：%s" % self.user)
        else:
            self.lbl_user.config(text="未登录")

    # ---------- ① 账号 ----------
    def _build_account(self):
        f = self.tab_account
        ttk.Label(f, text="用户名：").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        ttk.Label(f, text="密码：").grid(row=1, column=0, padx=10, pady=10, sticky="e")
        self.ent_user = ttk.Entry(f, width=28); self.ent_user.grid(row=0, column=1, sticky="w")
        self.ent_pwd = ttk.Entry(f, width=28, show="*"); self.ent_pwd.grid(row=1, column=1, sticky="w")
        ttk.Button(f, text="注册", command=self._do_register).grid(row=0, column=2, padx=8)
        ttk.Button(f, text="登录", command=self._login).grid(row=1, column=2, padx=8)
        ttk.Button(f, text="退出登录", command=self._logout).grid(row=2, column=2, padx=8)
        self.lbl_user = ttk.Label(f, text="未登录", foreground="#0a6")
        self.lbl_user.grid(row=2, column=0, columnspan=2, padx=10, sticky="w")
        ttk.Label(f, text="提示：各账号的简历/任务数据互相隔离；账号只存本地数据库。",
                  foreground="#888").grid(row=3, column=0, columnspan=3, padx=10, pady=10, sticky="w")

    def _do_register(self):
        ok, msg = auth.register(self.ent_user.get(), self.ent_pwd.get())
        log(msg); messagebox.showinfo("注册", msg)
        self._refresh_user_state()

    def _login(self):
        ok, msg = auth.login(self.ent_user.get(), self.ent_pwd.get())
        log(msg)
        if not ok:
            messagebox.showwarning("登录", msg)
        self._refresh_user_state()

    def _logout(self):
        auth.logout(); log("已退出登录"); self._refresh_user_state()

    # ---------- ② 简历 ----------
    def _build_resume(self):
        f = self.tab_resume
        self.ent_l0 = {}
        cols = 3
        for i, name in enumerate(schema.L0_FIELDS):
            r, c = divmod(i, cols)
            ttk.Label(f, text=name + "：").grid(row=r, column=c * 2, padx=4, pady=3, sticky="e")
            e = ttk.Entry(f, width=18)
            e.grid(row=r, column=c * 2 + 1, padx=4, pady=3, sticky="w")
            self.ent_l0[name] = e
        base = (len(schema.L0_FIELDS) + cols - 1) // cols
        ttk.Label(f, text="意向岗位：").grid(row=base, column=0, padx=4, pady=3, sticky="e")
        self.ent_intent = ttk.Entry(f, width=40)
        self.ent_intent.grid(row=base, column=1, columnspan=3, padx=4, pady=3, sticky="w")

        ttk.Label(f, text="经历（L2）：").grid(row=base + 1, column=0, padx=4, sticky="ne")
        self.tree_exp = ttk.Treeview(f, columns=("类型", "名称", "角色", "时间", "技术工具"),
                                     show="headings", height=7)
        for cname, w in (("类型", 80), ("名称", 180), ("角色", 90), ("时间", 110), ("技术工具", 160)):
            self.tree_exp.heading(cname, text=cname)
            self.tree_exp.column(cname, width=w)
        self.tree_exp.grid(row=base + 1, column=1, columnspan=4, padx=4, pady=3)
        bf = ttk.Frame(f); bf.grid(row=base + 2, column=1, columnspan=4, sticky="w", pady=4)
        ttk.Button(bf, text="添加经历", command=self._exp_add).pack(side="left", padx=4)
        ttk.Button(bf, text="删除选中", command=self._exp_del).pack(side="left", padx=4)
        ttk.Button(bf, text="导入简历(AI识别)", command=self._resume_import).pack(side="left", padx=16)
        ttk.Button(bf, text="保存简历", command=self._resume_save).pack(side="left", padx=4)
        ttk.Button(bf, text="重新加载", command=self._resume_load).pack(side="left", padx=4)

    def _exp_add(self):
        win = tk.Toplevel(self); win.title("添加经历"); win.grab_set()
        ents = {}
        for i, name in enumerate(schema.L2_FIELDS):
            ttk.Label(win, text=name + "：").grid(row=i, column=0, padx=6, pady=3, sticky="e")
            e = ttk.Entry(win, width=40); e.grid(row=i, column=1, padx=6, pady=3)
            ents[name] = e

        def ok():
            row = {k: e.get().strip() for k, e in ents.items()}
            if not row.get("名称"):
                messagebox.showwarning("经历", "名称不能为空", parent=win); return
            self.exp_rows.append(row)
            self.tree_exp.insert("", "end", values=(
                row.get("类型", ""), row.get("名称", ""), row.get("角色", ""),
                "%s~%s" % (row.get("时间起", ""), row.get("时间止", "")), row.get("技术工具", "")))
            win.destroy()
        ttk.Button(win, text="确定", command=ok).grid(row=len(schema.L2_FIELDS), column=1, pady=8, sticky="e")

    def _exp_del(self):
        for sel in self.tree_exp.selection():
            idx = self.tree_exp.index(sel)
            self.tree_exp.delete(sel)
            if 0 <= idx < len(self.exp_rows):
                self.exp_rows.pop(idx)

    def _resume_import(self):
        if not self.user:
            messagebox.showwarning("简历", "请先登录"); return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择简历文件",
            filetypes=[("简历文件", "*.txt *.md *.pdf *.docx"), ("所有文件", "*.*")])
        if not path:
            return
        log("识别简历中：%s ..." % path)

        def work():
            try:
                import resume_ai
                text = resume_ai.extract_text(path)
                parsed = resume_ai.smart_parse(text)
            except Exception as e:
                log("识别失败：%s" % e)
                return
            if not parsed:
                log("未能从文件中识别出字段")
                return
            self.event_generate("<<resume-parsed>>")
            # 回填到界面（主线程安全：用 after 包一层）
            def fill():
                for k, e in self.ent_l0.items():
                    if k in parsed:
                        e.delete(0, "end"); e.insert(0, str(parsed[k]))
                if parsed.get("意向岗位"):
                    self.ent_intent.delete(0, "end")
                    self.ent_intent.insert(0, parsed["意向岗位"])
                if parsed.get("技能"):
                    log("识别技能：%s" % "、".join(parsed["技能"]))
                for i in self.tree_exp.get_children():
                    self.tree_exp.delete(i)
                self.exp_rows = list(parsed.get("经历", []))
                for row in self.exp_rows:
                    self.tree_exp.insert("", "end", values=(
                        row.get("类型", ""), row.get("名称", ""), row.get("角色", ""),
                        "%s~%s" % (row.get("时间起", ""), row.get("时间止", "")),
                        row.get("技术工具", "")))
                log("识别完成：%d 个字段、%d 条经历，核对后点「保存简历」"
                    % (len([k for k in parsed if k != "经历"]), len(self.exp_rows)))
            self.after(0, fill)
        self._run(work)

    def _resume_save(self):
        if not self.user:
            messagebox.showwarning("简历", "请先登录"); return
        parsed = {k: e.get().strip() for k, e in self.ent_l0.items()}
        parsed["意向岗位"] = self.ent_intent.get().strip()
        parsed["经历"] = list(self.exp_rows)
        resume_store.save_resume(self.user, parsed)
        log("简历已保存（%d 条经历）" % len(self.exp_rows))
        messagebox.showinfo("简历", "已保存")

    def _resume_load(self):
        if not self.user:
            return
        data = resume_store.load_resume(self.user)
        if not data:
            log("还没有简历，填写后点保存"); return
        for k, e in self.ent_l0.items():
            e.delete(0, "end"); e.insert(0, data["l0"].get(k, ""))
        self.ent_intent.delete(0, "end"); self.ent_intent.insert(0, data.get("意向岗位", ""))
        for i in self.tree_exp.get_children():
            self.tree_exp.delete(i)
        self.exp_rows = list(data.get("experiences", []))
        for row in self.exp_rows:
            self.tree_exp.insert("", "end", values=(
                row.get("类型", ""), row.get("名称", ""), row.get("角色", ""),
                "%s~%s" % (row.get("时间起", ""), row.get("时间止", "")), row.get("技术工具", "")))
        log("简历已加载")

    # ---------- ③ 平台登录 ----------
    def _build_plogin(self):
        f = self.tab_plogin
        ttk.Label(f, text="平台：").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.cmb_pl = ttk.Combobox(f, values=list(platforms.PLATFORMS.keys()),
                                   state="readonly", width=12)
        self.cmb_pl.set("boss")
        self.cmb_pl.grid(row=0, column=1, sticky="w")
        self.cmb_pl.bind("<<ComboboxSelected>>", lambda _e: self._pl_status_refresh())
        self.lbl_pl_status = ttk.Label(f, text="未检测", foreground="#888")
        self.lbl_pl_status.grid(row=0, column=2, columnspan=3, padx=8, sticky="w")
        ttk.Button(f, text="刷新状态", command=self._pl_status_refresh).grid(row=0, column=5, padx=6)

        ttk.Button(f, text="扫码登录", command=self._pl_login_start).grid(row=1, column=0, padx=10, pady=6)
        ttk.Label(f, text="打开登录浏览器并在这里展示二维码，手机扫码后自动保存登录态",
                  foreground="#888").grid(row=1, column=1, columnspan=4, sticky="w")
        ttk.Button(f, text="在浏览器窗口中打开", command=self._pl_open_window).grid(row=2, column=0, padx=10, pady=6)
        ttk.Label(f, text="把登录浏览器窗口显示到桌面，适合直接对着窗口扫码",
                  foreground="#888").grid(row=2, column=1, columnspan=4, sticky="w")
        ttk.Button(f, text="退出该平台登录", command=self._pl_logout).grid(row=3, column=0, padx=10, pady=6)
        ttk.Label(f, text="清掉该平台登录态并关闭其浏览器（不影响其他平台）",
                  foreground="#888").grid(row=3, column=1, columnspan=4, sticky="w")
        ttk.Label(f, text="登录一次后浏览器保持驻留（屏幕外运行），检索/投递复用同一会话——"
                          "全程同一指纹，风控不易吊销。登录态被平台判失效时，"
                          "「抓取岗位」会提示回到本页签一键重登。",
                  foreground="#0a6", wraplength=620).grid(row=4, column=0, columnspan=6,
                                                          padx=10, pady=12, sticky="w")
        self._pl_status_refresh()

    def _pl_status_refresh(self):
        key = self.cmb_pl.get()
        colors = {"ok": "#0a6", "warn": "#a60", "bad": "#c00", "off": "#888"}

        def work():
            try:
                st = login_status.check_platform(key, online=False)
            except Exception as exc:
                self.after(0, lambda: self.lbl_pl_status.config(
                    text="检测失败：%s" % exc, foreground="#c00"))
                return
            self.after(0, lambda: self.lbl_pl_status.config(
                text="%s ｜ %s" % (st["label"], st["detail"]),
                foreground=colors.get(st["kind"], "#888")))
        self._run(work)

    def _pl_login_start(self):
        key = self.cmb_pl.get()
        if self._qr_win is not None and self._qr_win.winfo_exists():
            self._qr_win.lift()
            return
        log("正在打开 %s 登录页..." % key)

        def work():
            try:
                ok, msg = session.qr_login_start(key)
            except Exception as exc:
                err = str(exc)
                def fail():
                    log("打开登录页失败：%s" % err)
                    messagebox.showwarning("平台登录",
                                           "打开登录页失败：%s\n\n如提示依赖缺失，请安装 requirements-browser.txt" % err)
                self.after(0, fail)
                return
            self.after(0, lambda: (log("[%s] %s" % (key, msg)), self._qr_open(key)))
        self._run(work)

    def _qr_open(self, key):
        win = tk.Toplevel(self)
        win.title("%s 扫码登录" % key)
        win.geometry("380x560")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._qr_win = win
        lbl_img = ttk.Label(win)
        lbl_img.pack(pady=10)
        lbl_tip = ttk.Label(win, text="请用手机 App 扫描二维码登录", foreground="#0a6")
        lbl_tip.pack()
        bf = ttk.Frame(win); bf.pack(pady=8)

        def _load_img(path):
            try:
                img = tk.PhotoImage(file=path)
                lbl_img.configure(image=img)
                lbl_img.image = img  # 防 GC
                return True
            except Exception:
                return False

        state = {"tick": 0, "done": False}

        def _poll():
            if state["done"] or not win.winfo_exists():
                return
            state["tick"] += 1
            try:
                if session.qr_login_status(key):
                    state["done"] = True
                    lbl_tip.config(text="已扫码，正在保存登录态...", foreground="#0a6")
                    def _finish():
                        ok, msg = session.dpage_finish(key)
                        log("[%s] %s" % (key, msg))
                        self._pl_status_refresh()
                        lbl_tip.config(text=("✅ " + msg) if ok else ("❌ " + msg),
                                       foreground="#0a6" if ok else "#c00")
                        if ok:
                            win.after(1500, win.destroy)
                    threading.Thread(target=_finish, daemon=True).start()
                    return
                # 二维码会过期：每 ~30s 刷新一次截图（需要时重载页面换新码）
                if state["tick"] % 15 == 0:
                    ok, payload = session.qr_login_shot(key, reload=(state["tick"] % 60 == 0))
                    if ok:
                        _load_img(payload)
                    else:
                        lbl_tip.config(text="二维码刷新中...", foreground="#a60")
            except Exception:
                pass
            win.after(2000, _poll)

        def _reshot():
            ok, payload = session.qr_login_shot(key, reload=True)
            if ok:
                _load_img(payload)
                lbl_tip.config(text="已换新二维码，请重新扫描", foreground="#0a6")
            else:
                lbl_tip.config(text="刷新失败：%s" % payload, foreground="#c00")
        ttk.Button(bf, text="刷新二维码", command=_reshot).pack(side="left", padx=6)

        def _open_window():
            ok, msg = session.dpage_open(key)
            log("[%s] %s" % (key, msg))
            if ok:
                lbl_tip.config(text="浏览器窗口已打开，可对着窗口扫码", foreground="#0a6")
        ttk.Button(bf, text="在浏览器窗口打开", command=_open_window).pack(side="left", padx=6)

        if key == "mock":
            def _demo():
                ok, msg = session.qr_login_demo_scan(key)
                log("[%s] %s" % (key, msg))
            ttk.Button(bf, text="模拟扫码", command=_demo).pack(side="left", padx=6)
        ttk.Button(bf, text="关闭", command=win.destroy).pack(side="left", padx=6)

        shot = session.SESSION_DIR / ("%s_qr_live.png" % key)
        if not (_load_img(str(shot))):
            lbl_tip.config(text="二维码加载中，稍后自动出现...", foreground="#a60")
        win.after(2000, _poll)

    def _pl_open_window(self):
        key = self.cmb_pl.get()
        log("正在打开 %s 登录浏览器窗口..." % key)

        def work():
            try:
                ok, msg = session.dpage_open(key)
            except Exception as exc:
                self.after(0, lambda: (log("打开失败：%s" % exc),
                                       messagebox.showwarning("平台登录", str(exc))))
                return
            self.after(0, lambda: log("[%s] %s" % (key, msg)))
        self._run(work)

    def _pl_logout(self):
        key = self.cmb_pl.get()
        if not messagebox.askyesno("平台登录", "确定退出 %s 的登录吗？\n"
                                   "将清除本地登录态并关闭该平台浏览器。" % key):
            return
        session.clear_session(key)
        session.dpage_quit(key)
        log("已退出 %s 的登录" % key)
        self._pl_status_refresh()

    # ---------- ④ 抓取岗位 ----------
    def _build_search(self):
        f = self.tab_search
        keys = list(platforms.PLATFORMS.keys())
        ttk.Label(f, text="平台：").grid(row=0, column=0, padx=8, pady=8, sticky="e")
        self.cmb_platform = ttk.Combobox(f, values=keys, state="readonly", width=12)
        self.cmb_platform.set("boss"); self.cmb_platform.grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="关键词：").grid(row=0, column=2, padx=8, sticky="e")
        self.ent_kw = ttk.Entry(f, width=20); self.ent_kw.grid(row=0, column=3, sticky="w")
        ttk.Label(f, text="页数：").grid(row=1, column=0, padx=8, pady=8, sticky="e")
        self.spn_pages = ttk.Spinbox(f, from_=1, to=20, width=6); self.spn_pages.set(2)
        self.spn_pages.grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="城市代码（可空）：").grid(row=1, column=2, padx=8, sticky="e")
        self.ent_city = ttk.Entry(f, width=10); self.ent_city.grid(row=1, column=3, sticky="w")
        ttk.Button(f, text="开始检索", command=self._search).grid(row=0, column=4, rowspan=2, padx=16)
        ttk.Label(f, text="检索到的岗位经高强度字段校验+去重后入库。",
                  foreground="#888", wraplength=560).grid(row=2, column=0, columnspan=5, padx=8, sticky="w")
        ttk.Label(f, text="登录方式：先到「③ 平台登录」页签扫码登录，检索/投递会自动复用该登录态。",
                  foreground="#0a6", wraplength=560).grid(row=3, column=0, columnspan=5, padx=8, sticky="w")

    def _search(self):
        if not self.user:
            messagebox.showwarning("抓取", "请先登录"); return
        key = self.cmb_platform.get()
        kw = self.ent_kw.get().strip()
        if not kw:
            messagebox.showwarning("抓取", "关键词不能为空"); return
        pages = int(self.spn_pages.get())
        city = self.ent_city.get().strip()
        uid = resume_store.ensure_user_id(self.user)
        log("开始检索 %s：%s（%d 页）..." % (key, kw, pages))

        def work():
            import loop
            jobs, logs = loop.search_logged_in_platforms([key], kw, city=city, pages=pages)
            for _, m in logs:
                log("[%s] %s" % (key, m))
            if jobs:
                n = jobstore.store_jobs(jobs, user_id=uid)
                log("入库完成：%d 条" % n)
            else:
                log("未检索到岗位")
        self._run(work)

    # ---------- ⑤ 投递 ----------
    def _build_deliver(self):
        f = self.tab_deliver
        self.lbl_safe = ttk.Label(f, text="")
        self.lbl_safe.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="w")
        ttk.Button(f, text="生成投递任务", command=self._maketasks).grid(row=1, column=0, padx=10, pady=6)
        ttk.Label(f, text="把岗位库里在架岗位转为待投递任务（自动去重）",
                  foreground="#888").grid(row=1, column=1, columnspan=3, sticky="w")
        ttk.Label(f, text="单次条数：").grid(row=2, column=0, padx=10, sticky="e")
        self.spn_limit = ttk.Spinbox(f, from_=1, to=50, width=6); self.spn_limit.set(10)
        self.spn_limit.grid(row=2, column=1, sticky="w")
        ttk.Button(f, text="批量投递", command=lambda: self._deliver(False)).grid(row=2, column=2, padx=8)
        ttk.Button(f, text="全部投递", command=lambda: self._deliver(True)).grid(row=2, column=3, padx=8)
        self._refresh_safe()

    def _refresh_safe(self):
        if config.SAFE_MODE:
            self.lbl_safe.config(text="⚠ 安全模式已开启：投递只演练不真发（改 config.py 的 SAFE_MODE=False 才会真实投递）",
                                 foreground="#a60")
            return
        try:
            import delivery
            remaining = max(0, config.DAILY_SEND_LIMIT - delivery._daily_sends())
            self.lbl_safe.config(text=(
                "⚠ 安全模式已关闭：将真实投递，封号风险自负！ ｜ 节奏：每条随机 %d~%d 秒 ｜ "
                "今日剩余额度 %d/%d 条 ｜ 连续失败 %d 条自动熔断"
                % (config.DELIVER_INTERVAL_MIN, config.DELIVER_INTERVAL_MAX,
                   remaining, config.DAILY_SEND_LIMIT, config.MAX_CONSECUTIVE_FAILS)),
                foreground="#c00")
        except Exception:
            self.lbl_safe.config(text="⚠ 安全模式已关闭：将真实投递，封号风险自负！", foreground="#c00")

    def _maketasks(self):
        if not self.user:
            messagebox.showwarning("投递", "请先登录"); return
        uid = resume_store.ensure_user_id(self.user)
        log("生成投递任务...")

        def work():
            created = jobs_to_tasks(uid)
            log("新建 %d 个投递任务（已存在的自动跳过），到「任务追踪」查看" % created)
        self._run(work)

    def _deliver(self, all_pending):
        if not self.user:
            messagebox.showwarning("投递", "请先登录"); return
        uid = resume_store.ensure_user_id(self.user)
        if config.SAFE_MODE:
            if not messagebox.askyesno("安全模式", "安全模式开启中，本次只会演练不会真实投递。\n仍要继续吗？"):
                return
        limit = None if all_pending else int(self.spn_limit.get())
        log("开始%s投递（用户 %s）..." % ("全部" if all_pending else "批量", self.user))

        def work():
            import delivery
            res = delivery.deliver_batch(limit=limit, all_pending=all_pending)
            log(json.dumps({k: v for k, v in res.items() if k != "明细"}, ensure_ascii=False))
            for tid, ok, msg in res.get("明细", []):
                log("  任务%s %s %s" % (tid, "✅" if ok else "❌", msg))
            self.event_generate("<<tasks-changed>>")
            self.after(0, self._refresh_safe)  # 投递后刷新今日剩余额度
        self._run(work)

    # ---------- ⑥ 任务追踪 ----------
    def _build_tasks(self):
        f = self.tab_tasks
        self.lbl_counts = ttk.Label(f, text="")
        self.lbl_counts.grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Button(f, text="刷新", command=self._tasks_refresh).grid(row=0, column=5, padx=8)
        self.tree_tasks = ttk.Treeview(f, columns=("id", "岗位", "单位", "渠道", "状态", "结果"),
                                       show="headings", height=16)
        for cname, w in (("id", 50), ("岗位", 220), ("单位", 160), ("渠道", 70), ("状态", 80), ("结果", 200)):
            self.tree_tasks.heading(cname, text=cname)
            self.tree_tasks.column(cname, width=w)
        self.tree_tasks.grid(row=1, column=0, columnspan=6, padx=8, pady=4, sticky="nsew")
        f.rowconfigure(1, weight=1); f.columnconfigure(0, weight=1)
        self.bind("<<tasks-changed>>", lambda _e: self._tasks_refresh())

    def _tasks_refresh(self):
        for i in self.tree_tasks.get_children():
            self.tree_tasks.delete(i)
        if not self.user:
            self.lbl_counts.config(text="请先登录"); return
        uid = resume_store.ensure_user_id(self.user)
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT task_id, job_name, unit_name, entry_type, status, result"
            " FROM delivery_tasks WHERE user_id = ? ORDER BY task_id DESC LIMIT 500", (uid,)).fetchall()
        counts = {}
        for r in rows:
            self.tree_tasks.insert("", "end", values=(
                r["task_id"], r["job_name"], r["unit_name"], r["entry_type"], r["status"], r["result"]))
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        conn.close()
        self.lbl_counts.config(text="共 %d 条 | %s" % (len(rows), " ".join(
            "%s:%d" % kv for kv in sorted(counts.items()))))


def jobs_to_tasks(user_id):
    """岗位库在架岗位 → 当前账号的待投递任务（job_id+user_id 去重）。"""
    conn = db.get_conn()
    rows = conn.execute("SELECT job_id, fields FROM jobs WHERE active=1").fetchall()
    created = 0
    for r in rows:
        f = json.loads(r["fields"] if isinstance(r, dict) else r[1] or "{}")
        exists = conn.execute(
            "SELECT 1 FROM delivery_tasks WHERE job_id=? AND user_id=?",
            (r["job_id"] if isinstance(r, dict) else r[0], user_id)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, job_link,"
            " entry_type, entry_addr, status) VALUES (?,?,?,?,?,?,?,'待投递')",
            (r["job_id"] if isinstance(r, dict) else r[0], user_id,
             f.get("岗位名称", ""), f.get("单位名称", ""), f.get("岗位链接", ""),
             f.get("投递入口类型", ""), f.get("投递入口地址", "")))
        created += 1
    conn.commit()
    conn.close()
    return created


if __name__ == "__main__":
    db.init_db()
    App().mainloop()
