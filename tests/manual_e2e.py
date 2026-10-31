#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wbclean 端到端测试：临时目录造一套假数据，真实跑 clean / restore / cache。

单元测试只覆盖函数级逻辑，写入链路（备份、删库、删目录、还原）只能靠这个
脚本验证。它不是 CI 的一部分（需要真实跑 CLI），改完代码手工跑一遍：

    python tests/manual_e2e.py

只支持 Windows —— 里面有盘符大小写、正反斜杠双轨这些 Windows 专属断言。

不触碰真实数据目录：
  · 每条命令都强制带 --app-home <临时目录>
  · 备份目录随 --app-home 落到临时目录同级（不会写进 home）
  · 开跑前和收尾时校验真实库的 size+mtime 与 projects 目录数没变
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

if not sys.platform.startswith("win"):
    sys.exit("这个脚本只用于 Windows 本机验证")

PY = sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "bin", "wbclean")

REAL_HOME = os.path.join(os.path.expanduser("~"), ".workbuddy")
REAL_DB = os.path.join(REAL_HOME, "workbuddy.db")
REAL_PROJECTS = os.path.join(REAL_HOME, "projects")

FAILS = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  [ok]   %s" % name)
    else:
        print("  [FAIL] %s   %s" % (name, detail))
        FAILS.append(name)


def eq(name, got, want):
    check(name, got == want, "得到 %r，期望 %r" % (got, want))


def lsdir(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def run(args, expect_rc=0, extra_prefix=(), use_home=True):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["LOCALAPPDATA"] = LOCAL
    prefix = ["--app-home", HOME] if use_home else []
    cmd = [PY, SCRIPT] + prefix + list(extra_prefix) + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if expect_rc is not None and p.returncode != expect_rc:
        print("\n--- 命令失败: %s" % " ".join(args))
        print("rc =", p.returncode)
        print(p.stdout[-2500:])
        print(p.stderr[-1500:])
        FAILS.append("rc:" + " ".join(args))
    return p


def touch(path, size=1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)


def db_rows():
    conn = sqlite3.connect(DB)
    try:
        ws = [r[0] for r in conn.execute("SELECT path FROM workspaces ORDER BY path")]
        n_sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        soft = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE deleted_at IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    return ws, n_sess, soft


def real_fingerprint():
    st = os.stat(REAL_DB) if os.path.exists(REAL_DB) else None
    return (
        (st.st_size, int(st.st_mtime)) if st else None,
        len(lsdir(REAL_PROJECTS)),
    )


# ---------------------------------------------------------------- 环境搭建

ROOT = tempfile.mkdtemp(prefix="wbclean_e2e_")
HOME = os.path.join(ROOT, "apphome")
WSROOT = os.path.join(ROOT, "ws")
LOCAL = os.path.join(ROOT, "localappdata")
DB = os.path.join(HOME, "workbuddy.db")
BACKUP_DIR = os.path.join(ROOT, "WorkBuddy清理备份")

if os.path.realpath(HOME) == os.path.realpath(REAL_HOME):
    sys.exit("严重错误：临时数据目录等于真实数据目录，拒绝运行")
if not os.path.realpath(ROOT).startswith(os.path.realpath(tempfile.gettempdir())):
    sys.exit("严重错误：临时根目录不在系统临时目录内，拒绝运行")

REAL_BEFORE = real_fingerprint()

KEEP = os.path.join(WSROOT, "keepme")
GONE1 = os.path.join(WSROOT, "gone1")
GONE2 = os.path.join(WSROOT, "gone2")              # 入库用正斜杠
GONE3 = os.path.join(WSROOT, "gone3")              # 入库小写盘符，cwd 大写
ORPH_GONE = os.path.join(WSROOT, "orphan_gone")    # 路径不存在 + 有会话 cwd
ORPH_ALIVE = os.path.join(WSROOT, "orphan_alive")  # 路径存在 + 有会话 cwd
ORPH_DANGLING = os.path.join(WSROOT, "dangling")   # 路径不存在 + 无会话
ORPH_ALIVE2 = os.path.join(WSROOT, "alive_no_sess")  # 路径存在 + 无会话

os.makedirs(KEEP)
os.makedirs(ORPH_ALIVE)
os.makedirs(ORPH_ALIVE2)

import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
loader = importlib.machinery.SourceFileLoader("wbclean_mod", SCRIPT)
spec = importlib.util.spec_from_loader("wbclean_mod", loader)
M = importlib.util.module_from_spec(spec)
loader.exec_module(M)

key = M.project_dir_key
P = os.path.join(HOME, "projects")
K_KEEP, K_G1, K_G3 = key(KEEP), key(GONE1), key(GONE3)
K_OG, K_OA = key(ORPH_GONE), key(ORPH_ALIVE)
K_DG, K_OA2 = key(ORPH_DANGLING), key(ORPH_ALIVE2)

for name, size in ((K_KEEP, 4096), (K_G1, 8192), (K_G3, 5120),
                   (K_OG, 3072), (K_OA, 2048), (K_DG, 1024), (K_OA2, 1024)):
    touch(os.path.join(P, name, "history", "s1.jsonl"), size)

FILES = {
    "logs/2026-10-30/app.log": 4000,
    "logs/2026-10-31/app.log": 4000,
    "logs/2026-11-01/app.log": 4000,
    "logs/sandbox/sandbox.log": 3000,
    "cache/state.json": 1500,
    "app/cache/chunk.bin": 2500,
    "file-history/h1.bin": 3500,
    "changes-detail/c1.bin": 2200,
    "artifact-index/a1.idx": 1800,
    "blobs/keep.png": 5000,
}
for rel, size in FILES.items():
    touch(os.path.join(HOME, rel), size)
touch(os.path.join(LOCAL, "WorkBuddy", "logs", "main.log"), 1200)

DISPLAY = os.path.join(HOME, "workspace-display-names.json")
with open(DISPLAY, "w", encoding="utf-8") as f:
    json.dump({"workspaces": {
        KEEP: "保留的",
        GONE1: "已删的1",
        GONE2.replace("\\", "/"): "已删的2（正斜杠）",
        ORPH_GONE: "孤儿",
    }}, f, ensure_ascii=False, indent=2)

LOWER_G3 = GONE3[0].lower() + GONE3[1:]
UPPER_G3 = GONE3[0].upper() + GONE3[1:]

conn = sqlite3.connect(DB)
conn.executescript("""
CREATE TABLE workspaces (path TEXT PRIMARY KEY, last_opened_at INTEGER);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, cwd TEXT, status TEXT, deleted_at INTEGER
);
""")
now = int(time.time() * 1000)
conn.executemany("INSERT INTO workspaces VALUES (?,?)", [
    (KEEP, now),
    (GONE1, now - 1000),
    (GONE2.replace("\\", "/"), now - 2000),
    (LOWER_G3, now - 3000),
])
conn.executemany("INSERT INTO sessions VALUES (?,?,?,?)", [
    ("s1", KEEP, "done", None),
    ("s2", KEEP, "done", None),
    ("s3", GONE1, "done", now),
    ("s4", GONE1, "done", None),                     # 存活，必须保留
    ("s5", GONE2.replace("\\", "/"), "done", now),
    ("s6", GONE2.replace("\\", "/"), "done", now),
    ("s7", UPPER_G3, "done", now),                   # 大写盘符 + 软删
    ("s8", UPPER_G3, "done", None),                  # 大写盘符 + 存活
    ("s9", os.path.join(WSROOT, "other"), "done", now),   # 不属于任何工作空间
    ("s10", ORPH_GONE, "done", now),                 # 给孤儿目录反查真实路径
    ("s11", ORPH_ALIVE, "done", None),
])
conn.commit()
conn.close()

INIT_PROJECTS = lsdir(P)

print("\n临时数据目录：%s" % ROOT)

# ---------------------------------------------------------------- 环境自检

print("\n============================================================")
print(" 第 0 轮：环境自检（隔离是否真的生效）")
print("============================================================")

p = run(["report", "--format", "json"])
try:
    self_rep = json.loads(p.stdout)
except Exception as e:
    sys.exit("环境自检失败：report 输出的不是 JSON（%s）\n%s" % (e, p.stdout[:500]))

eq("report 指向临时数据目录", self_rep["app"]["app_home"], HOME)
eq("report 指向临时数据库", self_rep["app"]["db_path"], DB)
check("真实数据目录未被指向",
      not self_rep["app"]["app_home"].startswith(os.path.realpath(REAL_HOME)))
check("临时库已建好", os.path.exists(DB))
eq("自检时看到 4 条工作空间", self_rep["workspaces"]["total"], 4)
check("自定义目录提示走 stderr（不污染 JSON）",
      "自定义数据目录" in p.stderr and "自定义数据目录" not in p.stdout, p.stderr[:200])

print("\n============================================================")
print(" 第 1 轮：只读命令（scan / stats / report / cache）")
print("============================================================")

p = run(["scan"])
out = p.stdout
check("scan 统计 4 条工作空间",
      "工作空间记录 4 条：目录正常 1，目录已消失 3" in out, out[:600])
check("scan 统计 11 条会话 / 软删 6",
      "会话记录 11 条：其中已软删除 6 条" in out, out[:600])
check("scan 列出正斜杠目录 gone2", "gone2" in out)
check("scan 报出 2 个孤儿目录", "孤儿历史目录 2 个" in out, out[-800:])
check("scan 提示 2 个目录保留不动", "另有 2 个历史目录对应路径仍然存在" in out, out[-800:])
check("归一化生效：小写盘符目录统计到 2 条会话",
      "会话 2 条（软删 1 / 存活 1）" in out, out[:900])

p = run(["stats"])
check("stats 正常工作", p.returncode == 0 and "projects" in p.stdout.lower())
check("stats 显示 blobs", "blobs" in p.stdout)

check("report 文本模式正常",
      "诊断" in run(["report"]).stdout)

p = run(["report", "--format", "json"])
try:
    rep = json.loads(p.stdout)
    for k in ("tool", "version", "app", "workspaces", "sessions", "orphans",
              "disk", "suggestions"):
        check("report JSON 含 %s" % k, k in rep)
    eq("report 空壳数 = 3", rep["workspaces"]["dead"], 3)
    eq("report 孤儿数 = 2", rep["orphans"]["count"], 2)
    eq("report schema_ok", rep["app"]["schema_ok"], True)
    check("report 给出清理建议", len(rep["suggestions"]) >= 2, str(rep["suggestions"]))
except Exception as e:
    check("report JSON 可解析", False, "%s\n%s" % (e, p.stdout[:800]))

p = run(["cache"])
check("cache 只读列出日志", "logs" in p.stdout)
check("cache 只读提到 blobs 受保护", "blobs" in p.stdout)
check("cache 只读不改文件",
      os.path.exists(os.path.join(HOME, "logs", "2026-11-01", "app.log")))

print("\n============================================================")
print(" 第 2 轮：clean --dry-run（必须零写入）")
print("============================================================")

ws0, sess0, soft0 = db_rows()
p = run(["clean", "--dry-run", "--history", "--orphans"])
out = p.stdout
check("dry-run 打印目标数据库", DB in out, out[:500])
check("dry-run 提示未写入", "预览模式" in out)
check("dry-run 预览 3 条待删", "将删除 3 条" in out, out[:1500])
check("dry-run 列出历史文件夹", "会话历史文件夹" in out)
check("dry-run 列出孤儿目录", "孤儿历史目录：" in out)
eq("dry-run 后 workspaces 未变", db_rows()[0], ws0)
eq("dry-run 后 sessions 未变", db_rows()[1], sess0)
eq("dry-run 后 projects 未变", lsdir(P), INIT_PROJECTS)
check("dry-run 后 logs 未变", os.path.exists(os.path.join(HOME, "logs", "2026-11-01")))
check("dry-run 不产生备份", lsdir(BACKUP_DIR) == [], str(lsdir(BACKUP_DIR)))

print("\n============================================================")
print(" 第 3 轮：clean --yes（真实写入 + 备份）")
print("============================================================")

p = run(["clean", "--yes", "--history", "--orphans"], extra_prefix=("--skip-process-check",))
out = p.stdout
ws1, sess1, soft1 = db_rows()

eq("workspaces 只剩 1 条", len(ws1), 1)
eq("剩下的是活目录", ws1[0] if ws1 else None, KEEP)
# 11 条初始会话：删掉 4 条属于空壳工作空间的软删（s3/s5/s6/s7），
# s9 不在任何工作空间下、s10 属于孤儿目录，都不该被 clean 动
eq("sessions 剩 7 条", sess1, 7)
eq("软删会话剩 2 条（s9 / s10）", soft1, 2)

left = lsdir(P)
check("活工作空间历史保留", K_KEEP in left, str(left))
check("空壳1 历史已删", K_G1 not in left, str(left))
check("空壳3 历史已删（盘符大小写不同也命中）", K_G3 not in left, str(left))
check("孤儿（源路径消失）已删", K_OG not in left, str(left))
check("孤儿（源路径还在）保留", K_OA in left, str(left))
check("无会话但路径已消失，反解确认后删除", K_DG not in left, str(left))
check("无会话但路径还在，反解拦下不删", K_OA2 in left, str(left))
eq("projects 剩 3 个", len(left), 3)

check("输出提示完成", "完成" in out)
check("输出提示备份位置", "备份位置" in out)
check("输出提示回滚命令", "restore" in out)
check("列出保留的存活会话", "保留的存活会话" in out and "gone1" in out, out[-900:])

with open(DISPLAY, encoding="utf-8") as f:
    dn = json.load(f)["workspaces"]
eq("显示名剩 2 条", len(dn), 2)
check("显示名保留活的那条", KEEP in dn, str(dn))
check("显示名清掉空壳的", GONE1 not in dn, str(dn))
check("显示名保留孤儿目录那条", ORPH_GONE in dn, str(dn))

new_backups = lsdir(BACKUP_DIR)
check("备份落在临时目录（不写 home）", len(new_backups) == 1, str(new_backups))
BACKUP_NAME = new_backups[0] if new_backups else None
if BACKUP_NAME:
    bdir = os.path.join(BACKUP_DIR, BACKUP_NAME)
    check("备份含数据库", os.path.exists(os.path.join(bdir, "workbuddy.db")))
    check("备份含 meta.json", os.path.exists(os.path.join(bdir, "meta.json")))
    check("备份含显示名配置",
          os.path.exists(os.path.join(bdir, "workspace-display-names.json")))
    with open(os.path.join(bdir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    eq("备份 tag = before-clean", meta.get("tag"), "before-clean")
    eq("meta 记录平台", meta.get("platform"), sys.platform)

print("\n============================================================")
print(" 第 4 轮：幂等 —— 再跑一次 clean")
print("============================================================")

p = run(["clean", "--yes", "--history", "--orphans"], extra_prefix=("--skip-process-check",))
check("第二次 clean 报无需清理", "没有需要清理的内容" in p.stdout, p.stdout[-600:])
eq("第二次 clean 不改库", db_rows()[0], ws1)
eq("第二次 clean 不新增备份", len(lsdir(BACKUP_DIR)), 1)

print("\n============================================================")
print(" 第 5 轮：restore 回滚")
print("============================================================")

p = run(["restore"])
check("restore 无参数时列出可用备份",
      BACKUP_NAME is not None and BACKUP_NAME in p.stdout, p.stdout[-800:])

p = run(["restore", "不存在的备份", "--yes"],
        extra_prefix=("--skip-process-check",), expect_rc=1)
check("restore 不存在的备份时明确报错", "找不到备份" in p.stdout, p.stdout[-400:])

if BACKUP_NAME:
    p = run(["restore", BACKUP_NAME, "--yes"], extra_prefix=("--skip-process-check",))
    out = p.stdout
    ws2, sess2, soft2 = db_rows()
    eq("还原后 workspaces 回到 4 条", len(ws2), 4)
    eq("还原后 sessions 回到 11 条", sess2, 11)
    eq("还原后软删回到 6 条", soft2, 6)
    check("还原提示完成", "还原完成" in out)
    check("还原前自动另存", "另存" in out or "before-restore" in out)
    check("还原不动 projects（已删的历史不复活）",
          not os.path.isdir(os.path.join(P, K_G1)))
    check("还原生成了 before-restore 备份", len(lsdir(BACKUP_DIR)) == 2,
          str(lsdir(BACKUP_DIR)))

print("\n============================================================")
print(" 第 6 轮：cache --clean（安全项 / 深度项 / keep-days）")
print("============================================================")

run(["cache", "--clean", "--dry-run"])
check("cache dry-run 不删", os.path.exists(os.path.join(HOME, "cache", "state.json")))
p = run(["cache", "--clean", "--dry-run"])
check("cache dry-run 提示未删除", "预览模式" in p.stdout)
check("cache dry-run 打印数据目录", HOME in p.stdout, p.stdout[:400])
check("cache dry-run 提示还有深度项可清", "另有深度项" in p.stdout, p.stdout[:900])
check("cache 全览列出深度清理分区", "深度清理" in run(["cache"]).stdout)

run(["cache", "--clean", "--yes"], extra_prefix=("--skip-process-check",))
check("logs 已清空", not lsdir(os.path.join(HOME, "logs")))
check("cache 已清空", not lsdir(os.path.join(HOME, "cache")))
check("app/cache 已清空", not lsdir(os.path.join(HOME, "app", "cache")))
check("LocalAppData 日志已清空", not lsdir(os.path.join(LOCAL, "WorkBuddy", "logs")))
check("blobs 未动", os.path.exists(os.path.join(HOME, "blobs", "keep.png")))
check("深度项未动（未加 --deep）",
      os.path.exists(os.path.join(HOME, "file-history", "h1.bin")))
check("projects 未动", os.path.isdir(os.path.join(P, K_KEEP)))
check("数据库未动", os.path.exists(DB))

check("--deep 预览包含 file-history",
      "file-history" in run(["cache", "--clean", "--dry-run", "--deep"]).stdout)
run(["cache", "--clean", "--yes", "--deep"], extra_prefix=("--skip-process-check",))
check("--deep 后 file-history 清空", not lsdir(os.path.join(HOME, "file-history")))
check("--deep 后 changes-detail 清空", not lsdir(os.path.join(HOME, "changes-detail")))
check("--deep 后 artifact-index 清空", not lsdir(os.path.join(HOME, "artifact-index")))
check("--deep 后仍不动 blobs", os.path.exists(os.path.join(HOME, "blobs", "keep.png")))

for d in ("2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"):
    touch(os.path.join(HOME, "logs", d, "app.log"), 100)
run(["cache", "--clean", "--yes", "--keep-days", "2"], extra_prefix=("--skip-process-check",))
kept = lsdir(os.path.join(HOME, "logs"))
check("keep-days 2 保留 cutoff 之后两天",
      kept == ["2026-10-30", "2026-10-31"], str(kept))
check("keep-days 删掉更早的",
      not os.path.exists(os.path.join(HOME, "logs", "2026-10-28")))

print("\n============================================================")
print(" 第 7 轮：畸形环境（缺库 / 坏库 / 缺表 / 空目录）")
print("============================================================")

p = run(["--app-home", os.path.join(ROOT, "no_such_home"), "scan"],
        expect_rc=1, use_home=False)
check("缺数据库明确报错", "找不到数据库" in p.stdout, p.stdout[-400:])
check("缺数据库不抛裸 traceback", "Traceback" not in p.stdout)

bad = os.path.join(ROOT, "badhome")
os.makedirs(bad)
with open(os.path.join(bad, "workbuddy.db"), "wb") as f:
    f.write(b"this is not a sqlite file")
p = run(["--app-home", bad, "scan"], expect_rc=1, use_home=False)
check("坏库不崩溃（退出码 1）", p.returncode == 1)
check("坏库给中文错误", "出错" in p.stdout or "失败" in p.stdout, p.stdout[-500:])

empt = os.path.join(ROOT, "emptyhome")
os.makedirs(empt)
c = sqlite3.connect(os.path.join(empt, "workbuddy.db"))
c.executescript("CREATE TABLE dummy (id INTEGER);")
c.commit()
c.close()
p = run(["--app-home", empt, "scan"], expect_rc=2, use_home=False)
check("缺表时点名 workspaces",
      "workspaces" in p.stdout and ("缺失" in p.stdout or "缺少" in p.stdout),
      p.stdout[-600:])
check("缺表时退出码 2（区别于一般错误）", p.returncode == 2)
check("缺表时明确说不会继续",
      "不会继续" in p.stdout or "脚本不会" in p.stdout, p.stdout[-400:])
p = run(["--app-home", empt, "report", "--format", "json"], use_home=False)
try:
    r2 = json.loads(p.stdout)
    eq("缺表时 report schema_ok=False", r2["app"]["schema_ok"], False)
    check("缺表时 report 有建议", len(r2["suggestions"]) >= 1)
except Exception as e:
    check("缺表时 report 仍出合法 JSON", False, str(e))

p = run(["--app-home", empt, "cache"], expect_rc=0, use_home=False)
check("空数据目录下 cache 不报错", p.returncode == 0)
p = run(["--app-home", empt, "clean", "--dry-run"], expect_rc=2, use_home=False)
check("空壳库下 clean 拒绝执行并说明原因",
      "结构" in p.stdout and "缺失" in p.stdout, p.stdout[-400:])

print("\n============================================================")
print(" 第 8 轮：参数与路径边界")
print("============================================================")

p = run(["--version"])
check("--version 可用", "wbclean" in p.stdout and "." in p.stdout)
p = run(["--help"])
check("--help 可用", "usage" in p.stdout.lower())
p = run(["scan"])
check("--app-home 放在子命令前生效", "keepme" in p.stdout)

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["LOCALAPPDATA"] = LOCAL
env["WBCLEAN_APP_HOME"] = HOME
p = subprocess.run([PY, SCRIPT, "scan"], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env)
check("环境变量 WBCLEAN_APP_HOME 生效", "keepme" in p.stdout)
check("环境变量方式也提示自定义目录", "自定义数据目录" in p.stderr, p.stderr[:200])

p = run(["--app-home", ".", "scan"], expect_rc=None, use_home=False)
check("相对 --app-home 不崩（返回 0/1）", p.returncode in (0, 1))

p = run(["clean", "--yes", "--dry-run"], extra_prefix=("--skip-process-check",))
check("--dry-run 与 --yes 同用不报错", p.returncode == 0)

print("\n============================================================")
print(" 第 9 轮：真实数据目录零触碰校验")
print("============================================================")

REAL_AFTER = real_fingerprint()
eq("真实数据库 size+mtime 未变", REAL_AFTER[0], REAL_BEFORE[0])
eq("真实 projects 目录数未变", REAL_AFTER[1], REAL_BEFORE[1])

# ---------------------------------------------------------------- 收尾

print("\n============================================================")
print(" 收尾")
print("============================================================")
shutil.rmtree(ROOT, ignore_errors=True)
print("  已删除临时根目录 %s" % ROOT)
print("  备份目录随临时目录一起删除：%s" % BACKUP_DIR)

print("\n============================================================")
print(" 结果：%d 项检查，%d 项失败" % (CHECKS[0], len(FAILS)))
print("============================================================")
for f in FAILS:
    print("  FAIL:", f)
sys.exit(1 if FAILS else 0)
