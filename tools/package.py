#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打出 macOS 与 Windows 两个发布包。

    python3 tools/package.py              # 产物落在 dist/
    python3 tools/package.py --out /tmp   # 换个输出目录

产物：

    dist/wbclean-<版本>-macos.tar.gz      install.sh / wbclean.command
    dist/wbclean-<版本>-windows.zip       install.ps1 / wbclean.bat

两个包里的 bin/wbclean 是同一个文件，差别只在启动脚本：
macOS 包里的脚本 LF + 0755，Windows 包里 CRLF（.ps1 另加 UTF-8 BOM）。
这样处理是因为仓库在 Windows 上 checkout 过之后可能带 CRLF，
而带 CRLF 的 shebang 脚本在 macOS 上会报 bad interpreter；
反过来 .ps1 少了 BOM，Windows PowerShell 5.1 会按 GBK 解码导致中文乱码。

只用标准库，在哪个平台跑都行，不依赖系统 tar / zip 命令。
时间戳固定，同样的源码重复打两次字节一致。
"""

from __future__ import print_function

import argparse
import gzip
import hashlib
import io
import os
import re
import sys
import tarfile
import zipfile

# 固定时间戳（2010-01-01），保证可重复构建
FIXED_DATE = (2010, 1, 1, 0, 0, 0)
FIXED_EPOCH = 1262304000

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 平台 -> [(归档内路径, 源文件, 换行, 权限)]；bin/wbclean 两边都是 LF
PLATFORMS = {
    "macos": [
        ("bin/wbclean", "bin/wbclean", "lf", 0o755),
        ("install.sh", "install.sh", "lf", 0o755),
        ("wbclean.command", "wbclean.command", "lf", 0o755),
        ("README.md", "README.md", "lf", 0o644),
        ("LICENSE", "LICENSE", "lf", 0o644),
    ],
    "windows": [
        ("bin/wbclean", "bin/wbclean", "lf", 0o755),
        ("install.ps1", "install.ps1", "crlf-bom", 0o644),
        ("wbclean.bat", "wbclean.bat", "crlf", 0o644),
        ("README.md", "README.md", "crlf", 0o644),
        ("LICENSE", "LICENSE", "crlf", 0o644),
    ],
}


def read_version():
    with io.open(os.path.join(ROOT, "bin", "wbclean"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^VERSION\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    raise SystemExit("无法从 bin/wbclean 读取 VERSION")


def load(name, eol):
    """读源文件，按目标平台统一换行与 BOM。"""
    with io.open(os.path.join(ROOT, name), "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if eol == "lf":
        return text.encode("utf-8")
    if eol == "crlf":
        return text.replace("\n", "\r\n").encode("utf-8")
    if eol == "crlf-bom":
        return b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
    raise ValueError(eol)


def collect(platform):
    out = []
    for arc, src, eol, mode in sorted(PLATFORMS[platform]):
        path = os.path.join(ROOT, src)
        if not os.path.isfile(path):
            raise SystemExit("缺少文件：%s" % src)
        out.append((arc, load(src, eol), mode))
    return out


def write_zip(path, top, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data, mode in entries:
            info = zipfile.ZipInfo(top + "/" + arc, date_time=FIXED_DATE)
            # create_system 默认随构建机变化（Windows=0 / Unix=3），
            # 会让同一份源码在 mac 和 Windows 上打出不同的字节，
            # 发布页公布的 SHA256 就对不上了。这里钉死成 Unix（3），
            # 权限位本来就已经显式写在 external_attr 里。
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


def write_tar(path, top, entries):
    # gzip 头里默认会写当前时间和源文件名，抹掉这两样才能做到可重复构建
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                           mtime=FIXED_EPOCH, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w") as t:
                for arc, data, mode in entries:
                    info = tarfile.TarInfo(top + "/" + arc)
                    info.size = len(data)
                    info.mode = mode
                    info.mtime = FIXED_EPOCH
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    t.addfile(info, io.BytesIO(data))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="打 wbclean 发布包")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()

    version = read_version()
    if not os.path.isdir(args.out):
        os.makedirs(args.out)

    print("wbclean %s" % version)
    print("输出目录 %s" % args.out)
    print()

    results = []
    for platform in ("macos", "windows"):
        ext = ".tar.gz" if platform == "macos" else ".zip"
        name = "wbclean-%s-%s%s" % (version, platform, ext)
        dest = os.path.join(args.out, name)
        entries = collect(platform)
        if platform == "macos":
            write_tar(dest, name[: -len(ext)], entries)
        else:
            write_zip(dest, name[: -len(ext)], entries)
        results.append((name, dest))

    width = max(len(r[0]) for r in results)
    print("%-*s  %8s  %-64s  %s" % (width, "文件", "大小", "SHA256", "内容"))
    print("%s  %s  %s  %s" % ("-" * width, "-" * 8, "-" * 64, "-" * 24))
    for name, dest in results:
        platform = "macos" if name.endswith(".tar.gz") else "windows"
        files = ", ".join(e[0] for e in collect(platform))
        print("%-*s  %7.1fK  %s  %s" % (
            width, name, os.path.getsize(dest) / 1024.0, sha256(dest), files))
    print()
    print("上传到 GitHub Release：")
    for name, dest in results:
        print("  gh release upload v%s %s" % (version, os.path.join("dist", name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
