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

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_account = ttk.Frame(nb); nb.add(self.tab_account, text="① 账号")
        self.tab_resume = ttk.Frame(nb);  nb.add(self.tab_resume, text="② 简历")
        self.tab_search = ttk.Frame(nb);  nb.add(self.tab_search, text="③ 抓取岗位")
        self.tab_deliver = ttk.Frame(nb); nb.add(self.tab_deliver, text="④ 投递")
        self.tab_tasks = ttk.Frame(nb);   nb.add(self.tab_tasks, text="⑤ 任务追踪")

        self._build_account(); self._build_resume(); self._build_search()
        self._build_deliver(); self._build_tasks()

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

    # ---------- ③ 抓取岗位 ----------
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
        ttk.Label(f, text="检索到的岗位经高强度字段校验+去重后入库；真实平台请先登录并抓取登录态（见下方说明）。",
                  foreground="#888", wraplength=560).grid(row=2, column=0, columnspan=5, padx=8, sticky="w")
        ttk.Label(f, text="登录方式：在浏览器手动登录平台 → 终端执行 python main.py grab <平台>（Edge 需管理员）",
                  foreground="#888", wraplength=560).grid(row=3, column=0, columnspan=5, padx=8, sticky="w")

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

    # ---------- ④ 投递 ----------
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
        else:
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
        self._run(work)

    # ---------- ⑤ 任务追踪 ----------
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
