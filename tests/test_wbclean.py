#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wbclean 单元测试
================

跑法：
    python3 tests/test_wbclean.py
    python3 -m unittest discover -s tests -v

测试全程使用临时目录和临时数据库，**不会碰到真实的数据目录**。
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "bin", "wbclean")


def load_module():
    loader = importlib.machinery.SourceFileLoader("wbclean", SRC)
    spec = importlib.util.spec_from_loader("wbclean", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


mod = load_module()


SCHEMA_SQL = """
CREATE TABLE workspaces (path TEXT PRIMARY KEY, last_opened_at INTEGER);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, cwd TEXT, status TEXT, deleted_at INTEGER
);
"""


class DisplayWidthTests(unittest.TestCase):
    """中文宽度计算 —— 菜单对齐全靠它。"""

    def test_ascii_width(self):
        self.assertEqual(mod.dw("abc"), 3)
        self.assertEqual(mod.dw(""), 0)

    def test_chinese_counts_double(self):
        self.assertEqual(mod.dw("清理"), 4)
        self.assertEqual(mod.dw("清理空壳条目"), 12)

    def test_mixed(self):
        # "清理 + 删历史文件"
        self.assertEqual(mod.dw("清理 + 删历史文件"), 17)

    def test_pad_reaches_target_width(self):
        for name in ("诊断当前状态", "清理并删历史文件", "备份数据库"):
            padded = mod.pad(name, 16)
            self.assertEqual(mod.dw(padded), 16)

    def test_pad_never_truncates(self):
        self.assertEqual(mod.dw(mod.pad("很长很长很长", 4)) > 4, True)

    def test_pad_center(self):
        self.assertEqual(mod.dw(mod.pad("abc", 9, "center")), 9)


class SchemaTests(unittest.TestCase):
    """schema 探测 —— 版本不兼容时的保护网。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_db(self, sql=SCHEMA_SQL):
        conn = sqlite3.connect(self.db)
        conn.executescript(sql)
        conn.commit()
        return conn

    def test_missing_nothing(self):
        conn = self._make_db()
        self.assertEqual(mod.schema_missing(conn), [])
        conn.close()

    def test_missing_table(self):
        conn = self._make_db("CREATE TABLE dummy (id INTEGER);")
        missing = mod.schema_missing(conn)
        self.assertTrue(any("workspaces" in m for m in missing))
        self.assertTrue(any("sessions" in m for m in missing))
        conn.close()

    def test_missing_column(self):
        conn = self._make_db(
            "CREATE TABLE workspaces (path TEXT PRIMARY KEY, last_opened_at INTEGER);"
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, status TEXT);"
        )
        missing = mod.schema_missing(conn)
        self.assertEqual(missing, ["sessions.deleted_at（字段）"])
        conn.close()


class CollectTests(unittest.TestCase):
    """扫描逻辑 —— 判定空壳的依据。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.alive_dir = os.path.join(self.tmp, "alive")
        os.makedirs(self.alive_dir)
        # 空目录在 v1.4 起归类为「仅元数据」；要留在 alive 必须有可见文件
        with open(os.path.join(self.alive_dir, "work.txt"), "w") as f:
            f.write("x")
        self.dead_path = os.path.join(self.tmp, "gone")

        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO workspaces VALUES (?, ?)",
                     (self.alive_dir, 1791500000000))
        conn.execute("INSERT INTO workspaces VALUES (?, ?)",
                     (self.dead_path, 1791500000000))
        conn.execute(
            "INSERT INTO sessions VALUES ('s1', ?, 'completed', 1791500000000)",
            (self.dead_path,))
        conn.execute(
            "INSERT INTO sessions VALUES ('s2', ?, 'completed', NULL)",
            (self.dead_path,))
        conn.commit()
        conn.close()

        # 把被测函数的目录依赖指到空目录，避免误删任何东西
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_splits_alive_and_dead(self):
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        conn.close()
        self.assertEqual(len(data["alive"]), 1)
        self.assertEqual(len(data["dead"]), 1)
        self.assertEqual(data["dead"][0]["path"], self.dead_path)

    def test_counts_soft_deleted_sessions(self):
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        conn.close()
        dead = data["dead"][0]
        self.assertEqual(dead["sessions_total"], 2)
        self.assertEqual(dead["sessions_soft_deleted"], 1)
        self.assertEqual(dead["sessions_alive"], 1)

    def test_clean_only_removes_soft_deleted(self):
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        deleted_ws, deleted_sessions, skipped = mod.do_clean(
            conn, data["dead"], dry_run=False)
        conn.commit()
        conn.close()

        self.assertEqual(deleted_ws, 1)
        self.assertEqual(deleted_sessions, 1)      # 只删了软删的那条
        self.assertEqual(len(skipped), 1)          # 存活会话被标出
        self.assertEqual(skipped[0]["sessions_alive"], 1)

        conn = sqlite3.connect(self.db)
        left_ws = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        left_s = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id='s2'").fetchone()[0]
        conn.close()
        self.assertEqual(left_ws, 1)                # 存活的工作空间还在
        self.assertEqual(left_s, 1)                # 存活的会话还在

    def test_dry_run_changes_nothing(self):
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        before = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        mod.do_clean(conn, data["dead"], dry_run=True)
        after = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        conn.close()
        self.assertEqual(before, after)


class PathMappingTests(unittest.TestCase):
    """projects 目录名映射与越界防护。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_projects = mod.PROJECTS_DIR
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        os.makedirs(mod.PROJECTS_DIR)

    def tearDown(self):
        mod.PROJECTS_DIR = self.orig_projects
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_slash_becomes_dash(self):
        p = mod.project_dir_for("/Users/foo/WorkBuddy AI/2026-10-08-10-32-41")
        key = mod.project_dir_key(
            "/Users/foo/WorkBuddy AI/2026-10-08-10-32-41", is_win=False)
        self.assertTrue(key == "Users-foo-WorkBuddy AI-2026-10-08-10-32-41")
        self.assertTrue(p.endswith(key))

    def test_resolved_path_inside_projects(self):
        target = mod.project_dir_for("/Users/foo/x")
        self.assertTrue(mod.safe_under(target, mod.PROJECTS_DIR))

    def test_outside_path_rejected(self):
        self.assertFalse(mod.safe_under("/etc/passwd", mod.PROJECTS_DIR))
        self.assertFalse(mod.safe_under("/tmp", mod.PROJECTS_DIR))


class WindowsPathKeyTests(unittest.TestCase):
    """Windows 的 projects 目录名规则 —— 跟 macOS 不是同一套。

    这些用例在 macOS 上也会跑：project_dir_key 支持显式指定平台，
    所以 CI 两个系统上都能验证同一份逻辑，不用等到 Windows 才发现错。
    """

    def key(self, p):
        return mod.project_dir_key(p, is_win=True)

    def test_drive_lowercased_and_backslashes(self):
        self.assertEqual(
            self.key(r"C:\Users\Administrator\WorkBuddy\2026-08-06-14-46-01"),
            "c-Users-Administrator-WorkBuddy-2026-08-06-14-46-01")

    def test_forward_slashes_same_result(self):
        """库里同一个目录有正反两种写法，必须算出同一个 key。

        这是最容易踩的坑：按 macOS 那套「冒号换 -、分隔符换 -」
        算出来是 c--Users-...（两个横线），跟磁盘上的目录名对不上。
        """
        back = self.key(r"C:\Users\Administrator\WorkBuddy\2026-08-06-14-46-01")
        fwd = self.key("C:/Users/Administrator/WorkBuddy/2026-08-06-14-46-01")
        self.assertEqual(back, fwd)
        self.assertNotIn("--", back)

    def test_other_drive(self):
        self.assertEqual(
            self.key(r"D:\GitHub\A Struggle With Sin Walkthrough_0.62.0"),
            "d-GitHub-A Struggle With Sin Walkthrough_0.62.0")

    def test_trailing_separator_ignored(self):
        self.assertEqual(self.key("C:\\Users\\foo\\"),
                         self.key("C:\\Users\\foo"))

    def test_case_of_drive_only(self):
        """盘符统一小写，其余部分原样保留（用户目录可能真有大写）。"""
        self.assertEqual(self.key("c:\\Users\\Foo"),
                         self.key("C:\\Users\\Foo"))

    def test_reverse_key_roundtrip(self):
        path = r"C:\Users\Administrator\LightOps"
        key = self.key(path)
        self.assertEqual(mod.path_from_project_key(key, is_win=True), path)

    def test_macos_has_no_reverse(self):
        self.assertIsNone(mod.path_from_project_key("Users-foo-x", is_win=False))

    def test_reverse_keeps_timestamp_dashes(self):
        """时间戳目录名里的 - 不是分隔符，不能解成 2026\\10\\01\\15\\46\\26。"""
        # 反解要造一个 c-... 的键，非 Windows 上拿不到带盘符的真实路径
        if not mod.IS_WIN:
            self.skipTest("反解只在 Windows 上有真实路径可验")
        root = tempfile.mkdtemp(prefix="wbrev")
        try:
            ws = os.path.join(root, "2026-10-01-15-46-26")
            key = self.key(ws)
            self.assertEqual(mod.path_from_project_key(key, is_win=True), ws)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_reverse_prefers_existing_path(self):
        """带 - 的目录若真实存在，必须原样解回去。"""
        if not mod.IS_WIN:
            self.skipTest("反解只在 Windows 上有真实路径可验")
        root = tempfile.mkdtemp(prefix="wbrev")
        try:
            ws = os.path.join(root, "My-Project")
            os.makedirs(ws)
            self.assertEqual(
                mod.path_from_project_key(self.key(ws), is_win=True), ws)
        finally:
            shutil.rmtree(root, ignore_errors=True)


    def test_reverse_merges_timestamp_after_leaf_deleted(self):
        """叶子目录删了，时间戳那段仍要合回去 —— 靠「父目录存在 + 时间戳形状」。"""
        if not mod.IS_WIN:
            self.skipTest("反解只在 Windows 上有真实盘符路径可验")
        root = tempfile.mkdtemp(prefix="wbrev")
        try:
            ws = os.path.join(root, "WorkBuddy", "2026-10-01-15-46-26")
            os.makedirs(ws)
            key = self.key(ws)
            os.rmdir(ws)  # 工作空间删了，projects 下的历史目录还在
            self.assertEqual(mod.path_from_project_key(key, is_win=True), ws)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class NormPathTests(unittest.TestCase):
    """路径归一化 —— 会话归属统计能不能算准全靠它。"""

    def test_slashes_unified_on_windows(self):
        if not mod.IS_WIN:
            self.skipTest("只在 Windows 上有意义")
        self.assertEqual(mod.norm_path(r"C:\Users\a\b"),
                         mod.norm_path("C:/Users/a/b"))

    def test_case_unified_on_windows(self):
        if not mod.IS_WIN:
            self.skipTest("只在 Windows 上有意义")
        self.assertEqual(mod.norm_path(r"C:\Users\A\B"),
                         mod.norm_path(r"c:\users\a\b"))

    def test_trailing_separator_stripped(self):
        self.assertEqual(mod.norm_path("/tmp/a/"), mod.norm_path("/tmp/a"))

    def test_empty(self):
        self.assertEqual(mod.norm_path(""), "")
        self.assertEqual(mod.norm_path(None), "")


class CacheTests(unittest.TestCase):
    """缓存清理 —— 白名单与受保护目录的护栏。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_home = mod.APP_HOME
        mod.APP_HOME = self.tmp

    def tearDown(self):
        mod.APP_HOME = self.orig_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make(self, rel, size=1024):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full) or self.tmp, exist_ok=True)
        if full.endswith("/"):
            os.makedirs(full, exist_ok=True)
            return full
        with open(full, "wb") as f:
            f.write(b"\0" * size)
        return full

    def test_targets_cover_safe_and_deep(self):
        rows = mod.cache_targets()
        levels = set(r["level"] for r in rows)
        self.assertEqual(levels, {"safe", "deep"})
        names = [r["name"] for r in rows]
        self.assertIn("logs", names)
        self.assertIn("cache", names)

    def test_protected_paths_never_in_targets(self):
        """护栏：用户数据目录绝不能出现在清理白名单里。"""
        names = [r["name"] for r in mod.cache_targets()]
        forbidden = {"blobs", "projects", "app/session", "workbuddy.db",
                     "workspace", "artifact", "user"}
        for bad in forbidden:
            self.assertNotIn(bad, names,
                             "受保护路径 %s 不该出现在清理白名单" % bad)

    def test_targets_follow_app_home(self):
        """--app-home 改 APP_HOME 后，目标路径必须跟着变。

        Windows 上的 LocalAppData 日志是个例外：它本来就不在数据目录里，
        自带 root 字段声明边界，只要求落在自己声明的根内。
        """
        rows = mod.cache_targets()
        for r in rows:
            root = r.get("root", self.tmp)
            self.assertTrue(r["path"].startswith(root),
                            "%s 未跟随 APP_HOME" % r["name"])

    def test_purge_removes_everything(self):
        self._make("logs/a.log")
        self._make("logs/sub/b.log")
        freed = mod.purge_dir_contents(os.path.join(self.tmp, "logs"))
        self.assertGreater(freed, 0)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "logs")), [])

    def test_purge_keeps_directory_itself(self):
        self._make("cache/x.json")
        mod.purge_dir_contents(os.path.join(self.tmp, "cache"))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "cache")))

    def test_purge_by_date_respects_keep_days(self):
        today = time.strftime("%Y-%m-%d")
        old = time.strftime("%Y-%m-%d", time.localtime(time.time() - 10 * 86400))
        recent = time.strftime("%Y-%m-%d", time.localtime(time.time() - 1 * 86400))
        for d in (old, recent, today):
            self._make("logs/%s/x.log" % d)

        mod.purge_dir_contents(os.path.join(self.tmp, "logs"),
                               keep_days=3, by_date=True)
        left = set(os.listdir(os.path.join(self.tmp, "logs")))
        self.assertNotIn(old, left, "10 天前的日志应被删除")
        self.assertIn(recent, left, "1 天前的日志应保留")
        self.assertIn(today, left, "今天的日志应保留")

    def test_purge_by_date_zero_keep_days_removes_all(self):
        today = time.strftime("%Y-%m-%d")
        self._make("logs/%s/x.log" % today)
        mod.purge_dir_contents(os.path.join(self.tmp, "logs"),
                               keep_days=0, by_date=True)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "logs")), [])

    def test_purge_missing_dir_is_noop(self):
        self.assertEqual(
            mod.purge_dir_contents(os.path.join(self.tmp, "nope")), 0)


class SameDirTwoSpellingsTests(unittest.TestCase):
    """同一个目录在库里存了两种斜杠写法 —— 统计和删除都不能漏。

    Windows 上这是常态：文件系统给的是 C:\\Users\\a\\b，用户手输或命令行
    给的是 C:/Users/a/b。原版按 cwd 字符串精确匹配，一半会话会漏掉。
    """

    def setUp(self):
        if not mod.IS_WIN:
            self.skipTest("路径归一化差异只在 Windows 上出现")
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        # 空目录自 v1.4 起归「仅元数据」，本类要测的是 alive 分支，
        # 放个可见文件让它落在 alive 里
        with open(os.path.join(self.ws, "work.txt"), "w") as f:
            f.write("x")
        self.ws_fwd = self.ws.replace("\\", "/")

        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO workspaces VALUES (?, ?)", (self.ws, 1))
        # 三条软删 + 一条存活，正反斜杠各一半
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, 'done', 1)", (self.ws,))
        conn.execute("INSERT INTO sessions VALUES ('s2', ?, 'done', 1)", (self.ws_fwd,))
        conn.execute("INSERT INTO sessions VALUES ('s3', ?, 'done', 1)", (self.ws,))
        conn.execute("INSERT INTO sessions VALUES ('s4', ?, 'done', NULL)", (self.ws_fwd,))
        conn.commit()
        conn.close()

        self.orig_projects = mod.PROJECTS_DIR
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")

    def tearDown(self):
        mod.PROJECTS_DIR = self.orig_projects
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_both_spellings(self):
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        conn.close()
        self.assertEqual(len(data["alive"]), 1)
        item = data["alive"][0]
        self.assertEqual(item["sessions_total"], 4)
        self.assertEqual(item["sessions_soft_deleted"], 3)
        self.assertEqual(item["sessions_alive"], 1)

    def test_delete_catches_both_spellings(self):
        # 把目录删掉，让它变成空壳，走一遍真实删除路径
        shutil.rmtree(self.ws)
        conn = sqlite3.connect(self.db)
        data = mod.collect(conn, verify=True)
        self.assertEqual(len(data["dead"]), 1)
        mod.do_clean(conn, data["dead"])
        conn.commit()
        left = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        survive = conn.execute("SELECT id FROM sessions").fetchall()
        conn.close()
        self.assertEqual(left, 1, "只该剩下那条没软删的会话")
        self.assertEqual(survive[0][0], "s4")


class OrphanProjectTests(unittest.TestCase):
    """孤儿历史目录判定 —— 宁可少删，不能误删还在用的目录。"""

    SCHEMA = SCHEMA_SQL

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_projects = mod.PROJECTS_DIR
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        os.makedirs(mod.PROJECTS_DIR)

        self.alive = os.path.join(self.tmp, "alive")
        self.keep = os.path.join(self.tmp, "keepdir")
        self.gone = os.path.join(self.tmp, "gonedir")
        os.makedirs(self.alive)
        os.makedirs(self.keep)

        # 给每个目录造一份"历史"
        for p in (self.alive, self.keep, self.gone):
            d = os.path.join(mod.PROJECTS_DIR, mod.project_dir_key(p))
            os.makedirs(d)
            with open(os.path.join(d, "history.jsonl"), "wb") as f:
                f.write(b"\0" * 512)

        self.db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(self.db)
        conn.executescript(self.SCHEMA)
        conn.execute("INSERT INTO workspaces VALUES (?, ?)", (self.alive, 1))
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, 'done', NULL)",
                     (self.keep,))
        conn.execute("INSERT INTO sessions VALUES ('s2', ?, 'done', 1)",
                     (self.gone,))
        conn.commit()
        conn.close()

    def tearDown(self):
        mod.PROJECTS_DIR = self.orig_projects
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _find(self, rows, path):
        key = mod.project_dir_key(path)
        return [r for r in rows if r["name"] == key]

    def test_active_workspace_excluded(self):
        conn = sqlite3.connect(self.db)
        rows = mod.find_orphan_projects(conn)
        conn.close()
        self.assertEqual(self._find(rows, self.alive), [],
                         "现役工作空间的历史目录不算孤儿")

    def test_kept_when_target_still_exists(self):
        conn = sqlite3.connect(self.db)
        rows = mod.find_orphan_projects(conn)
        conn.close()
        hit = self._find(rows, self.keep)
        self.assertEqual(len(hit), 1)
        self.assertFalse(hit[0]["deletable"],
                         "目标目录还在，只是记录没了，不能删")
        self.assertTrue(hit[0]["source_exists"])

    def test_gone_target_is_deletable(self):
        conn = sqlite3.connect(self.db)
        rows = mod.find_orphan_projects(conn)
        conn.close()
        hit = self._find(rows, self.gone)
        self.assertEqual(len(hit), 1)
        self.assertTrue(hit[0]["deletable"])
        self.assertGreater(hit[0]["size"], 0)

    def test_missing_projects_dir_is_noop(self):
        mod.PROJECTS_DIR = os.path.join(self.tmp, "nope")
        conn = sqlite3.connect(self.db)
        self.assertEqual(mod.find_orphan_projects(conn), [])
        conn.close()


class HistorySourcePathTests(unittest.TestCase):
    """会话记录已删时，仍能从历史文件里读回工作空间路径。

    这是实盘踩出来的坑：macOS 上 path_from_project_key 永远返回 None，
    一旦 sessions.cwd 也查不到，find_orphan_projects 就把所有历史目录
    判成「疑似离线、保留不动」，--orphans 报 0 个，功能等于失效。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_projects = mod.PROJECTS_DIR
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")
        os.makedirs(mod.PROJECTS_DIR)

    def tearDown(self):
        mod.PROJECTS_DIR = self.orig_projects
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _hist(self, ws_path, folder_in_file=None, name="s1.jsonl"):
        """造一份历史目录，里面写一条带 Workspace Folder 的消息。"""
        d = os.path.join(mod.PROJECTS_DIR, mod.project_dir_key(ws_path))
        os.makedirs(d, exist_ok=True)
        shown = folder_in_file if folder_in_file is not None else ws_path
        line = ('{"type":"message","role":"user","content":[{"type":"input_text",'
                '"text":"<user_info>\\\\nWorkspace Folder: %s\\\\nNote: x"}]}\n'
                % shown)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(line)
        return d

    def test_reads_path_when_sessions_gone(self):
        """目录已删、sessions 也没有记录 —— 靠历史文件判成可删。"""
        gone = os.path.join(self.tmp, "gonedir")
        d = self._hist(gone)

        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        rows = mod.find_orphan_projects(conn)
        conn.close()

        hit = [r for r in rows if r["name"] == os.path.basename(d)]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["source_path"], gone)
        self.assertEqual(hit[0]["source_origin"], "history")
        self.assertTrue(hit[0]["deletable"],
                        "路径已不存在，这份孤儿历史应可清理")

    def test_kept_when_target_still_alive(self):
        """目标目录还在，只是工作空间记录没了 —— 必须保留。"""
        alive = os.path.join(self.tmp, "alivedir")
        os.makedirs(alive)
        self._hist(alive)

        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        rows = mod.find_orphan_projects(conn)
        conn.close()

        hit = [r for r in rows if r["source_path"] == alive]
        self.assertEqual(len(hit), 1)
        self.assertFalse(hit[0]["deletable"], "目标还在就不能删历史")

    def test_rejects_path_that_does_not_roundtrip(self):
        """文件里的路径编码后对不上目录名 —— 这条证据不采信，保持保守。"""
        gone = os.path.join(self.tmp, "gonedir")
        d = self._hist(gone, folder_in_file="/somewhere/else/entirely")

        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        rows = mod.find_orphan_projects(conn)
        conn.close()

        hit = [r for r in rows if r["name"] == os.path.basename(d)]
        self.assertEqual(len(hit), 1)
        # 核心不变式：错的那条路径绝不能变成删除依据
        self.assertNotEqual(hit[0]["source_path"], "/somewhere/else/entirely")
        self.assertNotEqual(hit[0]["source_origin"], "history")
        if not mod.IS_WIN:
            # macOS 反解必然为空，只剩「疑似离线」这一种结论
            self.assertIsNone(hit[0]["source_path"])
            self.assertEqual(hit[0]["source_state"], "suspect")
            self.assertFalse(hit[0]["deletable"])

    def test_sessions_takes_precedence(self):
        """sessions.cwd 有记录时优先用它，不去读文件。"""
        gone = os.path.join(self.tmp, "gonedir")
        d = self._hist(gone, folder_in_file="/wrong/path/here")

        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, 'done', NULL)", (gone,))
        rows = mod.find_orphan_projects(conn)
        conn.close()

        hit = [r for r in rows if r["name"] == os.path.basename(d)]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["source_origin"], "sessions")
        self.assertTrue(hit[0]["deletable"])


class WorkspaceStateTests(unittest.TestCase):
    """空壳三态判定 —— 磁盘没挂载不能当成目录被删。

    这是唯一会真删用户数据的分支：把「外置盘拔了」判成「目录删了」，
    等盘插回来，侧边栏条目已经没了，带 --history 时连会话历史一起没。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_projects = mod.PROJECTS_DIR
        mod.PROJECTS_DIR = os.path.join(self.tmp, "projects")

    def tearDown(self):
        mod.PROJECTS_DIR = self.orig_projects
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_dir_is_alive(self):
        p = os.path.join(self.tmp, "here")
        os.makedirs(p)
        self.assertEqual(mod.classify_workspace_path(p), ("alive", ""))

    def test_missing_leaf_with_existing_parent_is_dead(self):
        p = os.path.join(self.tmp, "gone")
        self.assertEqual(mod.classify_workspace_path(p)[0], "dead")

    def test_missing_parent_chain_is_suspect(self):
        p = os.path.join(self.tmp, "unmounted", "proj")
        state, reason = mod.classify_workspace_path(p)
        self.assertEqual(state, "suspect")
        self.assertTrue(reason, "疑似离线必须给出原因")

    def test_unmounted_volume_is_suspect(self):
        if mod.IS_WIN:
            self.skipTest("/Volumes 是 macOS 的卷挂载点")
        state, reason = mod.classify_workspace_path(
            "/Volumes/NoSuchVolume-wbclean-test/proj")
        self.assertEqual(state, "suspect")
        self.assertIn("/Volumes", reason)

    def _db_with(self, paths):
        db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA_SQL)
        for p in paths:
            conn.execute("INSERT INTO workspaces VALUES (?, ?)", (p, 1))
        conn.commit()
        conn.close()
        return db

    def test_collect_keeps_suspect_out_of_dead(self):
        alive = os.path.join(self.tmp, "alive")
        os.makedirs(alive)
        # 空目录自 v1.4 起归「仅元数据」，这里要的是 alive，放个可见文件
        with open(os.path.join(alive, "work.txt"), "w") as f:
            f.write("x")
        gone = os.path.join(self.tmp, "gone")
        unmounted = os.path.join(self.tmp, "unmounted", "proj")
        db = self._db_with([alive, gone, unmounted])

        conn = sqlite3.connect(db)
        data = mod.collect(conn, verify=True)
        conn.close()

        self.assertEqual(len(data["alive"]), 1)
        self.assertEqual(len(data["dead"]), 1)
        self.assertEqual(len(data["suspect"]), 1)
        self.assertEqual(data["suspect"][0]["path"], unmounted)
        self.assertNotIn(unmounted, [i["path"] for i in data["dead"]])

    def _clean_args(self, db, force=False):
        from types import SimpleNamespace
        return SimpleNamespace(db=db, dry_run=True, yes=True, history=True,
                               sessions=False, orphans=False, force=force)

    def test_dry_run_reports_suspect_without_counting_it(self):
        gone = os.path.join(self.tmp, "gone")
        unmounted = os.path.join(self.tmp, "unmounted", "proj")
        db = self._db_with([gone, unmounted])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_clean(self._clean_args(db))
        out = buf.getvalue()

        self.assertIn("疑似离线", out)
        self.assertIn("将删除 1 条", out, "只该把确定已删除的那条算进清理目标")

    def test_force_includes_suspect(self):
        gone = os.path.join(self.tmp, "gone")
        unmounted = os.path.join(self.tmp, "unmounted", "proj")
        db = self._db_with([gone, unmounted])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_clean(self._clean_args(db, force=True))
        out = buf.getvalue()

        self.assertIn("[疑似离线 · --force]", out)
        self.assertIn("将删除 2 条", out)


class KeepDaysSemanticsTests(unittest.TestCase):
    """--keep-days 的承诺是「保留最近 N 天，含今天」。

    两个坑：cutoff 按 now-N*86400 取日期，实际保留 N+1 天；
    非日期条目（sandbox/、*.old.log）压根不看 keep_days，无条件删。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _day(self, offset):
        name = time.strftime("%Y-%m-%d",
                             time.localtime(time.time() - offset * 86400))
        d = os.path.join(self.logs, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "x.log"), "w") as f:
            f.write("x" * 100)
        return name

    def test_keep_one_day_means_today_only(self):
        today, yesterday = self._day(0), self._day(1)
        mod.purge_dir_contents(self.logs, keep_days=1, by_date=True)
        left = set(os.listdir(self.logs))
        self.assertIn(today, left)
        self.assertNotIn(yesterday, left, "keep-days=1 不该留下昨天的日志")

    def test_keep_three_days_is_today_plus_two(self):
        d0, d1, d2, d3 = (self._day(0), self._day(1),
                          self._day(2), self._day(3))
        mod.purge_dir_contents(self.logs, keep_days=3, by_date=True)
        left = set(os.listdir(self.logs))
        for keep in (d0, d1, d2):
            self.assertIn(keep, left)
        self.assertNotIn(d3, left)

    def test_non_date_entries_follow_mtime(self):
        fresh = os.path.join(self.logs, "sandbox")
        os.makedirs(fresh)
        old = os.path.join(self.logs, "daemon.old.log")
        with open(old, "w") as f:
            f.write("z" * 10)
        now = time.time()
        os.utime(fresh, (now, now))
        os.utime(old, (now - 5 * 86400, now - 5 * 86400))

        mod.purge_dir_contents(self.logs, keep_days=1, by_date=True)
        left = set(os.listdir(self.logs))
        self.assertIn("sandbox", left, "当天还在写的沙箱日志不能删")
        self.assertNotIn("daemon.old.log", left)

    def test_zero_keep_days_removes_everything(self):
        self._day(0)
        os.makedirs(os.path.join(self.logs, "sandbox"))
        mod.purge_dir_contents(self.logs, keep_days=0, by_date=True)
        self.assertEqual(os.listdir(self.logs), [])


class DbPrecedenceTests(unittest.TestCase):
    """--db 与 --app-home 的优先级：显式 --db 必须赢。

    原来 main() 只要发现 app_home 就无条件 args.db = DB_PATH，
    而 app_home 的默认值又来自 WBCLEAN_APP_HOME 环境变量 ——
    等于环境里设了这个变量，--db 就被静默吞掉。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home_a = os.path.join(self.tmp, "a")
        self.home_b = os.path.join(self.tmp, "b")
        os.makedirs(self.home_a)
        os.makedirs(self.home_b)
        self._make_db(os.path.join(self.home_a, "workbuddy.db"), 1)
        self._make_db(os.path.join(self.home_b, "workbuddy.db"), 3)
        self.saved = (mod.APP_HOME, mod.DB_PATH, mod.DISPLAY_NAMES_PATH,
                      mod.PROJECTS_DIR, sys.argv)

    def tearDown(self):
        (mod.APP_HOME, mod.DB_PATH, mod.DISPLAY_NAMES_PATH,
         mod.PROJECTS_DIR, sys.argv) = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_db(self, path, n):
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA_SQL)
        for i in range(n):
            p = os.path.join(self.tmp, "ws-%s-%d"
                             % (os.path.basename(os.path.dirname(path)), i))
            os.makedirs(p, exist_ok=True)
            conn.execute("INSERT INTO workspaces VALUES (?, ?)", (p, 1))
        conn.commit()
        conn.close()

    def _run(self, argv):
        buf = io.StringIO()
        sys.argv = ["wbclean"] + argv
        with contextlib.redirect_stdout(buf):
            mod.main()
        return buf.getvalue()

    def test_explicit_db_beats_app_home(self):
        out = self._run(["--app-home", self.home_a,
                         "--db", os.path.join(self.home_b, "workbuddy.db"),
                         "scan"])
        self.assertIn("工作空间记录 3 条", out,
                      "显式 --db 指向的库有 3 条，读到 1 条说明被覆盖了")

    def test_app_home_used_when_db_absent(self):
        out = self._run(["--app-home", self.home_b, "scan"])
        self.assertIn("工作空间记录 3 条", out)


class MetadataOnlyTests(unittest.TestCase):
    """「仅元数据」判定 —— 顶层只有隐藏元数据的目录也算实质空壳。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mk(self, rel, content=None):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full) or self.tmp, exist_ok=True)
        if content is None:
            os.makedirs(full, exist_ok=True)
        else:
            with open(full, "w") as f:
                f.write(content)
        return full

    def test_empty_dir_has_no_visible_content(self):
        d = self._mk("empty")
        self.assertFalse(mod.has_visible_content(d))

    def test_only_hidden_entries(self):
        self._mk("m/.workbuddy-ai/memory/x.md", "log")
        self._mk("m/.DS_Store", "")
        self.assertFalse(mod.has_visible_content(os.path.join(self.tmp, "m")))

    def test_visible_file_counts(self):
        d = self._mk("w/code.py", "print(1)")
        self.assertTrue(mod.has_visible_content(d))

    def test_hidden_plus_visible_counts(self):
        d = self._mk("w2/.workbuddy-ai/memory/x.md", "log")
        self._mk("w2/note.txt", "hello")
        self.assertTrue(mod.has_visible_content(d))

    def test_missing_dir_treated_as_having_content(self):
        """访问不了按「有内容」处理 —— 宁可保守。"""
        self.assertTrue(mod.has_visible_content(os.path.join(self.tmp, "nope")))

    def test_collect_classifies_metadata_only(self):
        self._mk("ws/.workbuddy-ai/memory/x.md", "log")
        d = os.path.join(self.tmp, "ws")   # 工作空间目录，不是里面的文件
        db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO workspaces VALUES (?, ?)", (d, 1))
        conn.commit()

        data = mod.collect(conn, verify=True)
        conn.close()
        self.assertEqual(len(data["metadata_only"]), 1)
        self.assertEqual(data["metadata_only"][0]["path"], d)
        self.assertEqual(len(data["alive"]), 0)
        self.assertEqual(data["metadata_only"][0]["state"], "metadata_only")

    def test_collect_alive_with_real_file(self):
        self._mk("ws/.workbuddy-ai/memory/x.md", "log")
        self._mk("ws/note.txt", "hello")
        d = os.path.join(self.tmp, "ws")   # 工作空间目录，不是里面的文件
        db = os.path.join(self.tmp, "t.db")
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO workspaces VALUES (?, ?)", (d, 1))
        conn.commit()

        data = mod.collect(conn, verify=True)
        conn.close()
        self.assertEqual(len(data["alive"]), 1)
        self.assertEqual(len(data["metadata_only"]), 0)


class WindowsCompatTests(unittest.TestCase):
    """Windows 特有行为 —— 隐藏属性、元数据目录名、只读文件删除。

    这些用例在 macOS 上跑时通过 monkeypatch 模拟 Windows 语义，
    保证跨平台改动不会只在开发机上正确。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_win = mod.IS_WIN

    def tearDown(self):
        mod.IS_WIN = self.orig_win
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dot_prefix_is_hidden_on_both_platforms(self):
        for is_win in (False, True):
            mod.IS_WIN = is_win
            self.assertTrue(mod._is_hidden_entry(".workbuddy-ai", None))
            self.assertTrue(mod._is_hidden_entry(".DS_Store", None))

    def test_windows_hidden_attribute_counts(self):
        """Windows 上隐藏是属性不是命名 —— 不带点的隐藏目录也要认。"""
        class FakeStat:
            st_file_attributes = 0x2          # FILE_ATTRIBUTE_HIDDEN
        real_stat = os.stat
        mod.IS_WIN = True
        os.stat = lambda p: FakeStat()
        try:
            self.assertTrue(mod._is_hidden_entry("SecretDir", "/x/SecretDir"))
        finally:
            os.stat = real_stat

    def test_windows_normal_dir_not_hidden(self):
        class FakeStat:
            st_file_attributes = 0x0
        real_stat = os.stat
        mod.IS_WIN = True
        os.stat = lambda p: FakeStat()
        try:
            self.assertFalse(mod._is_hidden_entry("NormalDir", "/x/NormalDir"))
        finally:
            os.stat = real_stat

    def test_unix_non_dot_not_hidden(self):
        mod.IS_WIN = False
        self.assertFalse(mod._is_hidden_entry("NormalDir", "/x/NormalDir"))

    def test_stat_failure_treated_as_visible(self):
        """读不到隐藏属性时按「可见」处理，宁可多算。"""
        real_stat = os.stat
        mod.IS_WIN = True
        def boom(p):
            raise OSError("denied")
        os.stat = boom
        try:
            self.assertFalse(mod._is_hidden_entry("X", "/x/X"))
        finally:
            os.stat = real_stat

    def test_windows_metadata_dir_name(self):
        """Windows 的元数据目录是 .workbuddy，不是 .workbuddy-ai。"""
        d = os.path.join(self.tmp, "ws")
        os.makedirs(os.path.join(d, ".workbuddy", "memory"))
        with open(os.path.join(d, ".workbuddy", "memory", "a.md"), "w") as f:
            f.write("log")
        self.assertFalse(mod.has_visible_content(d))

    def test_count_memory_files_both_names(self):
        d = os.path.join(self.tmp, "ws2")
        os.makedirs(os.path.join(d, ".workbuddy-ai", "memory"))
        os.makedirs(os.path.join(d, ".workbuddy", "memory"))
        with open(os.path.join(d, ".workbuddy-ai", "memory", "x.md"), "w") as f:
            f.write("l")
        with open(os.path.join(d, ".workbuddy", "memory", "y.md"), "w") as f:
            f.write("l")
        self.assertEqual(mod.count_memory_files(d), 2)

    def test_count_memory_files_missing_dir(self):
        self.assertEqual(mod.count_memory_files(os.path.join(self.tmp, "nope")), 0)

    def test_remove_tree_deletes_nested(self):
        t = os.path.join(self.tmp, "todel")
        os.makedirs(os.path.join(t, "a", "b"))
        with open(os.path.join(t, "a", "b", "f.txt"), "w") as f:
            f.write("x")
        mod.remove_tree(t)
        self.assertFalse(os.path.exists(t))

    def test_remove_tree_handles_readonly_file(self):
        """模拟 Windows 只读属性：chmod 0500 后普通 rmtree 会失败。"""
        t = os.path.join(self.tmp, "ro")
        os.makedirs(t)
        f = os.path.join(t, "locked.txt")
        with open(f, "w") as x:
            x.write("x")
        os.chmod(f, 0o500)
        try:
            mod.remove_tree(t)
            self.assertFalse(os.path.exists(t))
        finally:
            if os.path.exists(t):
                os.chmod(f, 0o700)


class PluginGovernanceTests(unittest.TestCase):
    """插件治理 —— 旧版本识别、在用版本保护、禁用标记写入。

    这块的判据必须有据可依，不能靠猜：应用会给升级后留下的旧版本目录
    打 .orphaned_at 标记，测试同时覆盖「有标记」和「无标记但不在清单里」
    两种路径，以及最要紧的一条 —— 在用版本永远不能被当成残留。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_home = mod.APP_HOME
        mod.APP_HOME = self.tmp
        self.cache = os.path.join(self.tmp, "plugins", "cache")
        os.makedirs(self.cache, exist_ok=True)

    def tearDown(self):
        mod.APP_HOME = self.orig_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _version(self, marketplace, plugin, version, size=64, orphaned=False):
        d = os.path.join(self.cache, marketplace, plugin, version)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "payload.bin"), "wb") as f:
            f.write(b"\0" * size)
        if orphaned:
            with open(os.path.join(d, ".orphaned_at"), "w") as f:
                f.write("1700000000000")
        return d

    def _manifest(self, mapping):
        """写 installed_plugins.json。mapping: {插件键: 版本目录名}"""
        path = os.path.join(self.tmp, "plugins", "installed_plugins.json")
        plugins = {}
        for key, version in mapping.items():
            plugin, marketplace = key.split("@", 1)
            plugins[key] = [{
                "scope": "user",
                "installPath": os.path.join(self.cache, marketplace, plugin, version),
                "version": version,
            }]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "plugins": plugins}, f)

    def _settings(self, enabled=None):
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"enabledPlugins": enabled or {}}, f, indent=2)
        return path

    def test_live_version_is_never_removable(self):
        """清单指向的版本必须判为 live，绝不能进可清理列表。"""
        self._version("workbuddy-builtin", "demo", "2.0.0")
        self._version("workbuddy-builtin", "demo", "1.0.0", orphaned=True)
        self._manifest({"demo@workbuddy-builtin": "2.0.0"})

        rows, summary = mod.scan_plugins()
        by_version = {r["version"]: r for r in rows}

        self.assertEqual(by_version["2.0.0"]["state"], "live")
        self.assertEqual(by_version["1.0.0"]["state"], "orphan")

        removable = mod.removable_plugin_rows(rows)
        self.assertEqual([r["version"] for r in removable], ["1.0.0"])
        self.assertEqual(summary["live"], 1)
        self.assertEqual(summary["orphan"], 1)

    def test_orphan_marker_alone_is_enough(self):
        """没有清单记录，但带 .orphaned_at —— 判定为可清理。"""
        self._version("cb_teams_marketplace", "finance-data", "1.6.0", orphaned=True)
        self._manifest({})

        rows, _ = mod.scan_plugins()
        self.assertEqual(rows[0]["state"], "orphan")
        self.assertEqual(len(mod.removable_plugin_rows(rows)), 1)

    def test_unregistered_without_marker_is_stale_not_live(self):
        """插件整个不在清单里，且没有标记 —— 归为 stale，仍可清理。"""
        self._version("some-market", "ghost", "0.1.0")
        self._manifest({})

        rows, _ = mod.scan_plugins()
        self.assertEqual(rows[0]["state"], "stale")
        self.assertEqual(len(mod.removable_plugin_rows(rows)), 1)

    def test_non_live_version_without_marker_is_orphan(self):
        """有在用版本、本份不在清单里且无标记 —— 按残留处理，不留在「在用」里。"""
        self._version("m", "p", "2.0.0")
        self._version("m", "p", "1.0.0")
        self._manifest({"p@m": "2.0.0"})

        rows, _ = mod.scan_plugins()
        states = {r["version"]: r["state"] for r in rows}
        self.assertEqual(states, {"2.0.0": "live", "1.0.0": "orphan"})

    def test_summary_sizes_add_up(self):
        self._version("m", "p", "2.0.0", size=100)
        self._version("m", "p", "1.0.0", size=200, orphaned=True)
        self._manifest({"p@m": "2.0.0"})

        _rows, summary = mod.scan_plugins()
        self.assertEqual(summary["live_size"], 100)
        # 孤儿版本还带一个 .orphaned_at 文件（内容 13 字节：1700000000000），
        # 按真实字节数统计，不能只算 payload
        marker_bytes = len("1700000000000")
        self.assertEqual(summary["orphan_size"], 200 + marker_bytes)

    def test_missing_cache_dir_is_not_an_error(self):
        """缓存目录不存在时返回空结果，不抛异常。"""
        shutil.rmtree(self.cache, ignore_errors=True)
        rows, summary = mod.scan_plugins()
        self.assertEqual(rows, [])
        self.assertEqual(summary["orphan"], 0)

    def test_corrupt_manifest_degrades_gracefully(self):
        """清单损坏时扫描仍要能跑，把版本归为 stale 而不是崩溃。"""
        self._version("m", "p", "1.0.0")
        path = os.path.join(self.tmp, "plugins", "installed_plugins.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")

        rows, _ = mod.scan_plugins()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "stale")

    def test_disable_writes_marker_and_keeps_other_keys(self):
        """禁用只改目标键，其余设置原样保留。"""
        path = self._settings({"keep@m": True, "target@m": True})
        with open(path, "r", encoding="utf-8") as f:
            original = json.load(f)
        original["sandbox"] = {"extraAllowWrite": ["~/x"]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(original, f, indent=2)

        mod.update_enabled_plugins({"target@m": False})

        with open(path, "r", encoding="utf-8") as f:
            after = json.load(f)
        self.assertFalse(after["enabledPlugins"]["target@m"])
        self.assertTrue(after["enabledPlugins"]["keep@m"])
        self.assertEqual(after["sandbox"], {"extraAllowWrite": ["~/x"]})

    def test_disable_is_idempotent(self):
        path = self._settings({"prev@m": False})
        for _ in range(3):
            mod.update_enabled_plugins({"prev@m": False})
        with open(path, "r", encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(after["enabledPlugins"], {"prev@m": False})

    def test_enable_round_trips(self):
        path = self._settings({"x@m": False})
        mod.update_enabled_plugins({"x@m": True})
        with open(path, "r", encoding="utf-8") as f:
            self.assertTrue(json.load(f)["enabledPlugins"]["x@m"])

    def test_missing_settings_raises_rather_than_creating(self):
        """settings.json 不存在时报错，不能凭空造一个出来。"""
        with self.assertRaises(IOError):
            mod.update_enabled_plugins({"a@m": False})

    def test_invalid_settings_json_is_not_overwritten(self):
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ broken")
        with self.assertRaises(IOError):
            mod.update_enabled_plugins({"a@m": False})
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{ broken")

    def test_output_stays_valid_json_with_unicode(self):
        """写回后必须仍是合法 JSON，中文路径不能被转义破坏。"""
        path = self._settings({})
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["note"] = "中文备注"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        mod.update_enabled_plugins({"新@市场": False})
        with open(path, "r", encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(after["note"], "中文备注")
        self.assertFalse(after["enabledPlugins"]["新@市场"])

    def test_remove_refuses_path_outside_cache(self):
        """越界护栏：不在插件缓存目录内的一律拒绝。"""
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with self.assertRaises((IOError, OSError)):
            mod.remove_plugin_version(outside, self.cache)

    def test_remove_deletes_only_target(self):
        keep = self._version("m", "p", "2.0.0")
        drop = self._version("m", "p", "1.0.0", orphaned=True)
        self._manifest({"p@m": "2.0.0"})

        rows, _ = mod.scan_plugins()
        for r in mod.removable_plugin_rows(rows):
            mod.remove_plugin_version(r["path"], self.cache)

        self.assertTrue(os.path.isdir(keep))
        self.assertFalse(os.path.exists(drop))

    def test_resolve_plugin_key_accepts_short_and_full(self):
        self._version("builtin", "mcp-miora", "1.0.0")
        rows, _ = mod.scan_plugins()
        self.assertEqual(mod.resolve_plugin_key(rows, "mcp-miora"),
                         "mcp-miora@builtin")
        self.assertEqual(mod.resolve_plugin_key(rows, "mcp-miora@builtin"),
                         "mcp-miora@builtin")

    def test_resolve_plugin_key_rejects_ambiguous_short_name(self):
        self._version("m1", "dup", "1.0.0")
        self._version("m2", "dup", "1.0.0")
        rows, _ = mod.scan_plugins()
        with self.assertRaises(ValueError):
            mod.resolve_plugin_key(rows, "dup")

    def test_resolve_plugin_key_unknown_returns_none(self):
        self._version("m", "p", "1.0.0")
        rows, _ = mod.scan_plugins()
        self.assertIsNone(mod.resolve_plugin_key(rows, "no-such-plugin"))


class FileReleaseGuardTests(unittest.TestCase):
    """插件清理的前置检查：只看文件本身，不看数据库。

    背景：应用运行时数据库一直被 Electron 持有，但插件缓存里的旧版本目录
    通常没有任何进程打开。用「数据库被占」去拦插件清理属于误伤 ——
    原来就是这么拦的，导致明明能安全删的旧版本删不掉。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unused_path_reports_no_hits(self):
        p = os.path.join(self.tmp, "idle")
        os.makedirs(p)
        with open(os.path.join(p, "f.txt"), "w") as f:
            f.write("x")
        self.assertEqual(mod.files_in_use([p]), [])

    @unittest.skipIf(mod.IS_WIN, "Windows 上没有 lsof")
    @unittest.skipUnless(shutil.which("lsof"), "需要 lsof")
    def test_open_file_is_detected(self):
        """真打开一个文件，lsof 应当能查出来。"""
        p = os.path.join(self.tmp, "held.txt")
        with open(p, "w") as f:
            f.write("x")
            f.flush()
            # 子进程持有句柄，父进程关掉也不释放
            holder = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys,time;"
                 "fh=open(sys.argv[1],'r');"
                 "time.sleep(30)", p])
            try:
                time.sleep(0.6)
                hits = mod.files_in_use([p])
                self.assertTrue(hits, "打开中的文件应当被检出")
                self.assertTrue(any(pid for pid, _path in hits))
            finally:
                holder.terminate()
                holder.wait(timeout=5)

    def test_require_files_released_passes_when_idle(self):
        p = os.path.join(self.tmp, "idle2")
        os.makedirs(p)
        with contextlib.redirect_stdout(io.StringIO()):
            mod.require_files_released([p])      # 不应抛异常

    @unittest.skipIf(mod.IS_WIN, "Windows 上没有 lsof")
    @unittest.skipUnless(shutil.which("lsof"), "需要 lsof")
    def test_require_files_released_aborts_when_held(self):
        p = os.path.join(self.tmp, "busy.txt")
        with open(p, "w") as f:
            f.write("x")
            f.flush()
            holder = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys,time;"
                 "fh=open(sys.argv[1],'r');"
                 "time.sleep(30)", p])
            try:
                time.sleep(0.6)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    with self.assertRaises(SystemExit):
                        mod.require_files_released([p])
                self.assertIn("正被进程占用", buf.getvalue())
            finally:
                holder.terminate()
                holder.wait(timeout=5)


class MarketplaceSourceTests(unittest.TestCase):
    """市场源副本：自定义市场会在 marketplaces/<市场> 下留一份解包内容。

    这份和 plugins/cache 里的已装版本是两回事 —— 删掉源不影响已装插件，
    但重装时要重新下载。所以只允许在 --purge --purge-source 下动它。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_home = mod.APP_HOME
        mod.APP_HOME = self.tmp
        self.root = os.path.join(self.tmp, "plugins")
        self.cache = os.path.join(self.root, "cache")
        self.markets = os.path.join(self.root, "marketplaces")
        os.makedirs(self.cache, exist_ok=True)
        os.makedirs(self.markets, exist_ok=True)

    def tearDown(self):
        mod.APP_HOME = self.orig_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _source(self, marketplace, size=128):
        d = os.path.join(self.markets, marketplace, "plugin")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "bin.bin"), "wb") as f:
            f.write(b"\0" * size)
        return os.path.join(self.markets, marketplace)

    def test_source_path_and_size(self):
        self._source("my-market", size=256)
        p = mod.marketplace_source_path("my-market")
        self.assertTrue(os.path.isdir(p))
        self.assertEqual(mod.marketplace_source_size("my-market"), 256)

    def test_missing_source_is_zero(self):
        self.assertEqual(mod.marketplace_source_size("nope"), 0)

    def test_cache_scan_ignores_marketplace_sources(self):
        """marketplaces/ 不是版本目录，不该被当成插件版本扫进去。"""
        self._source("my-market")
        vdir = os.path.join(self.cache, "my-market", "demo", "1.0.0")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "f"), "w") as f:
            f.write("x")

        rows, _ = mod.scan_plugins()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plugin"], "demo")

    def test_remove_source_refuses_outside_marketplaces(self):
        outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(outside)
        with self.assertRaises((IOError, OSError)):
            mod.remove_plugin_version(
                outside, os.path.join(self.root, "marketplaces"))

    def test_remove_source_works_under_marketplaces(self):
        p = self._source("gone-market")
        mod.remove_plugin_version(p, self.markets)
        self.assertFalse(os.path.exists(p))

    def test_source_survives_cache_clean(self):
        """清旧版本残留时不能动市场源 —— 那是另一码事。"""
        self._source("keep-market")
        vdir = os.path.join(self.cache, "keep-market", "demo", "1.0.0")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "f"), "w") as f:
            f.write("x")
        with open(os.path.join(vdir, ".orphaned_at"), "w") as f:
            f.write("1")

        rows, _ = mod.scan_plugins()
        for r in mod.removable_plugin_rows(rows):
            mod.remove_plugin_version(r["path"], self.cache)

        self.assertTrue(os.path.isdir(
            mod.marketplace_source_path("keep-market")))


class LauncherTests(unittest.TestCase):
    """双击启动器必须同时支持「命令行用法」。

    历史 bug：两个启动器都把 menu 写死、从不转发参数，于是
    `wbclean.bat scan` / `./wbclean.command scan` 一律弹交互菜单。
    """

    def setUp(self):
        self.root = os.path.dirname(HERE)

    def _read(self, name):
        with open(os.path.join(self.root, name), "rb") as f:
            return f.read()

    def test_windows_launcher_forwards_arguments(self):
        bat = self._read("wbclean.bat").decode("ascii")
        self.assertIn("%*", bat, "没把 %* 转给 Python，参数会丢")
        self.assertIn('if "%~1"==""', bat, "缺「有参数 / 双击」分流")

    def test_windows_launcher_stays_ascii_and_crlf(self):
        """OEM 代码页会把中文搞乱，所以 .bat 必须纯 ASCII + CRLF。"""
        raw = self._read("wbclean.bat")
        self.assertTrue(all(b < 128 for b in raw), "wbclean.bat 混进了非 ASCII 字符")
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), "wbclean.bat 混进了裸 LF")

    def test_macos_launcher_forwards_arguments(self):
        cmd = self._read("wbclean.command").decode("utf-8")
        self.assertIn('"$@"', cmd, "没把 $@ 转给 Python，参数会丢")

    def test_macos_launcher_skips_clear_in_cli_mode(self):
        """命令行模式不能 clear —— 会把上一条命令的输出抹掉。"""
        cmd = self._read("wbclean.command").decode("utf-8")
        cli_branch = cmd.split('exec "$WBCLEAN" "$@"')[0]
        self.assertIn('[ "$#" -gt 0 ]', cli_branch)
        self.assertNotIn("clear", cli_branch)


    def test_macos_launcher_prefers_bundled_copy(self):
        """包内自带的必须优先于 PATH 里已安装的旧版。"""
        cmd = self._read("wbclean.command").decode("utf-8")
        bundled = cmd.index('-x "./bin/wbclean"')
        installed = cmd.index("command -v wbclean")
        self.assertLess(bundled, installed,
                        "PATH 里的旧版抢在包内新版前面了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
