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

import importlib.machinery
import importlib.util
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
        self.assertTrue(p.endswith(
            "Users-foo-WorkBuddy AI-2026-10-08-10-32-41"))

    def test_resolved_path_inside_projects(self):
        target = mod.project_dir_for("/Users/foo/x")
        self.assertTrue(mod.safe_under(target, mod.PROJECTS_DIR))

    def test_outside_path_rejected(self):
        self.assertFalse(mod.safe_under("/etc/passwd", mod.PROJECTS_DIR))
        self.assertFalse(mod.safe_under("/tmp", mod.PROJECTS_DIR))


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
        """--app-home 改 APP_HOME 后，目标路径必须跟着变。"""
        rows = mod.cache_targets()
        for r in rows:
            self.assertTrue(r["path"].startswith(self.tmp),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
