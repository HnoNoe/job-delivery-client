"""客户端无头回归：账号 → 简历 → 抓取(mock) → 建任务 → 投递 → 任务追踪。

运行：python verify_client.py（改 auth/resume_store/delivery 后必跑）。
注意：本文件须最先设置 JOBDELIVERY_DB（在任何项目 import 之前），否则配置快照不生效。
"""
import json
import os
import sys

os.environ["JOBDELIVERY_DB"] = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "data", "_verify_client.db"))

import auth
import config
import db
import jobstore
import resume_store


def main():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                              (" | " + str(detail)) if (detail and not cond) else ""))
        if not cond:
            ok = False

    db.init_db()
    # 独立测试库（导入前已设 JOBDELIVERY_DB），每次重建保证幂等
    if os.path.exists(os.environ["JOBDELIVERY_DB"]):
        os.remove(os.environ["JOBDELIVERY_DB"])
    db.init_db()

    print("=== 账号 ===")
    check("注册过短用户名被拒", not auth.register("a", "123456")[0])
    check("注册过短密码被拒", not auth.register("测试员", "123")[0])
    ok1, _ = auth.register("测试员", "abc12345")
    check("正常注册成功", ok1)
    check("重复注册被拒", not auth.register("测试员", "abc12345")[0])
    check("错误密码登录被拒", not auth.login("测试员", "wrong000")[0])
    check("正确登录成功", auth.login("测试员", "abc12345")[0])
    check("会话保持", auth.current_user() == "测试员")
    auth.logout()
    check("退出后会话清空", auth.current_user() is None)

    print("=== 简历（与网页版同构）===")
    auth.login("测试员", "abc12345")
    parsed = {"姓名": "张同学", "学校": "四川大学", "专业": "计算机科学",
              "意向岗位": "后端工程师",
              "经历": [{"类型": "项目", "名称": "订单系统", "角色": "后端", "技术工具": "Python、MySQL"}]}
    uid = resume_store.save_resume("测试员", parsed)
    data = resume_store.load_resume("测试员")
    check("L0 字段往返一致", data["l0"].get("学校") == "四川大学")
    check("意向岗位保存", data["意向岗位"] == "后端工程师")
    check("经历条数与内容", len(data["experiences"]) == 1
          and data["experiences"][0]["名称"] == "订单系统")
    auth.login("另一个人", "xyz12345") if auth.register("另一个人", "xyz12345")[0] else None
    other = resume_store.load_resume("另一个人")
    check("账号数据隔离（他人简历独立）",
          other is None or other["l0"].get("学校") != "四川大学")

    print("=== 抓取→建任务→投递 ===")
    auth.login("测试员", "abc12345")
    n = jobstore.store_jobs([
        {"岗位名称": "客户端测试岗A", "单位名称": "甲公司", "薪资": "10-15K",
         "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:5001/wapi/zpgeek/friend/add.json"},
        {"岗位名称": "客户端测试岗B", "单位名称": "乙公司"},
    ], user_id=uid)
    check("岗位入库 2 条", n == 2, n)
    import client
    created = client.jobs_to_tasks(uid)
    check("建任务 2 条", created == 2, created)
    created2 = client.jobs_to_tasks(uid)
    check("建任务幂等（重复为 0）", created2 == 0, created2)
    conn = db.get_conn()
    nt = conn.execute("SELECT COUNT(*) c FROM delivery_tasks WHERE user_id=?", (uid,)).fetchone()["c"]
    conn.close()
    check("任务追踪查询（当前用户 2 条）", nt == 2, nt)
    res = __import__("delivery").deliver_batch(limit=1)
    check("安全模式拦截真实投递", res["投递数"] == 0 and "安全模式" in res["停止原因"])

    print()
    print("=== 客户端回归", "通过 ===" if ok else "存在 FAIL ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
