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
import os
import shutil
import sqlite3
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
