# AGENTS.md

给 AI 助手的项目规则。开工前读一遍，动代码前再读一遍。

## 这是什么项目

WorkBuddy 数据目录的清理工具。macOS / Windows 双平台，**单文件 Python**（`bin/wbclean`），
零第三方依赖，只用标准库。

```
bin/wbclean        主程序（唯一的源码文件）
tests/             单元测试，纯 unittest
tools/package.py   打发布包，跨平台可跑，重复构建字节一致
wbclean.bat        Windows 双击启动器（纯 ASCII + CRLF）
wbclean.command    macOS 双击启动器（LF + 0755）
install.sh / .ps1  安装器，装完在 PATH 里放个包装器
```

它删的是用户磁盘上的真实文件。**所有规则的前提是：宁可少删，不可错删。**

---

## 先跑测试

```bash
python3 tests/test_wbclean.py
```

**不要用 pytest** —— 没装，也不在依赖里。测试全程用临时目录和临时数据库。

提交前必须全绿。CI 在 macOS / Ubuntu / Windows × Python 3.9 / 3.13 上跑同一份测试。

---

## 绝对禁止

### 数据安全

- **禁止**用 `--skip-process-check` 绕过 `require_app_closed()`。向被 WorkBuddy（Electron）
  持锁的 SQLite 写入有损坏风险。会话本身跑在 WorkBuddy 里时写命令必然被拦，
  正确做法是生成脚本让用户退出应用后执行，不是绕过护栏。
- **禁止**把新路径加进缓存清理白名单（`bin/wbclean` 约 1914 行）。白名单之外一律不碰；
  白名单里只放「删了会自动重建」的东西。
- **禁止**写「清理一切匹配 X 的文件」这类逻辑。只删能明确证明是垃圾的东西。
- **禁止**在没有 dry-run 的情况下执行删除。流程固定为：
  `--dry-run` 给用户看 → 用户确认 → 加 `--yes` 执行 → `scan` 复核。
- **禁止**在测试里指向真实数据目录。必须 `tempfile.mkdtemp()` + 临时 SQLite。
- **禁止**动用户的备份目录（默认 `~/WorkBuddy清理备份/`）。

### 编码与换行

| 文件 | 要求 |
| :--- | :--- |
| `bin/wbclean`、`install.sh`、`wbclean.command`、`tools/package.py` | **LF** + 可执行位 |
| `*.bat`、`*.ps1` | **CRLF**；`.ps1` 另需 UTF-8 BOM |
| `wbclean.bat` | **纯 ASCII** |

`wbclean.bat` 保持纯 ASCII 不是洁癖：OEM 代码页会在 `chcp 65001` 生效前把中文搞乱。
注释也写英文。

不要改 `.gitattributes` 里的换行规则，除非同时改 `tools/package.py` 和 CI 的包校验。

### 结构与依赖

- **不加第三方依赖**。只用标准库。
- **不拆** `bin/wbclean` 成多文件。单文件是刻意设计（拷一个文件就能跑）。
- **不引** pytest / black / ruff 之类，除非同时改 CI 和文档。

### 版本与发布

- **不擅自改 `VERSION`**。只有明确要发版时才动。
- **改了行为就要动 `BUILD`**（构建日期常量，在文件顶部）。同版本号可能被重构建，
  BUILD 用来区分用户跑的是哪一版 —— 排查问题时靠它。
- **改了行为就要同步 README 的版本历史表**。
- **不擅自打 tag、不 force push `main`**。

---

## 改代码的规矩

- **修 bug 先写复现测试**，确认它在旧代码上转红，再改实现让它转绿。
  反向验证很便宜，能挡住「以为修好了」。
- **加功能必须带测试**。测试名用中文 docstring 说明「在防什么」。
- **平台差异用 `IS_WIN` / `IS_MAC`**，不要在代码里散落 `sys.platform == ...`。
- **平台专属的测试必须加 skip 守卫**。CI 在三个系统上跑同一份测试，
  一条只在 Windows 成立的断言写在没守卫的测试里，main 会直接红。
- **改测试要有理由**。测试写错了可以改，但要在提交信息里说清楚「原来的断言为什么不对」，
  不能为了让 CI 变绿而放宽断言。
- **用户可见文案用中文**，代码注释用中文，标识符用英文。

---

## 提交与分支

- 分支开发，走 PR，CI 全绿再合 `main`。
- 提交信息用 conventional commits 前缀（`fix:` / `feat:` / `test:` / `docs:` / `ci:`），
  正文中文，说清**根因**而不只是现象。
- 一个提交一件事。

---

## 已知的坑

- **测退出码不要接管道**：`cmd | tail` 会把真实退出码吞掉，看到的永远是 0。
- **沙箱里 `ps` 常报 operation not permitted**，读进程改用 `lsof` / `pgrep`。
- **`importlib.machinery` 要显式 import**，只 import `importlib.util` 会 AttributeError。
- **CI 里不要在 cmd 步骤跑 `wbclean.bat`**：它的 `chcp 65001` 会搅坏 runner 的 stdout
  管道，命令执行了、退出码也对，但日志一行都抓不到。启动器的功能测试放在
  `tests/test_wbclean.py` 的 `LauncherTests` 里用 `subprocess` 跑。
- **改 CRLF 文件不要用文本编辑器**，用 Python 以 `rb`/`wb` 精确替换，否则整文件换行翻转，
  diff 变成全文重写。

---

## 发布流程

```bash
python3 tests/test_wbclean.py        # 全绿
python3 tools/package.py             # 产物落 dist/
# 校验可重复构建（CI 的 package job 会做同样的事）
git tag -a vX.Y -m "release: vX.Y"
```

README 的版本历史、`VERSION`、`BUILD` 三处必须同步。
