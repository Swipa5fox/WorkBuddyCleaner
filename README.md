# WorkBuddy Cleaner

![Version](https://img.shields.io/badge/version-1.4-blue.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.7%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

> **WorkBuddy 清理器** —— 清掉侧边栏里那些「本地文件夹已经不存在」的空壳工作空间条目。
> 命令行工具名：`wbclean`

WorkBuddy 的侧边栏「空间」分组只能一条条右键「从列表中移除」，没有批量入口。

用久了就会积累一堆：文件夹早就删了，数据库里的记录还留着，列表一直堆在那儿。
这个工具就是干这件事的——把这些空壳条目一次清掉，顺手带个诊断、备份、还原和
磁盘占用统计。

macOS 和 Windows 用的是**同一份代码**，差别只在数据目录、进程检测和路径规则上，
具体见 [Windows 说明](#windows-说明)。

---

## 目录

- [这是什么](#这是什么)
- [下载](#下载)
- [免责声明](#免责声明)
- [安装](#安装)
- [用法](#用法)
- [Windows 说明](#windows-说明)
- [工作原理](#工作原理)
- [安全设计](#安全设计)
- [兼容性](#兼容性)
- [版本历史](#版本历史)
- [常见问题](#常见问题)
- [反馈问题](#反馈问题)
- [许可](#许可)

---

## 这是什么

一个**只做一件事**的命令行工具：清理 WorkBuddy 工作空间列表里的空壳条目。

交互式菜单长这样：

```
   ==============================================================
                         WorkBuddy 数据维护
   ==============================================================

   1   诊断当前状态      随时可用，不用退应用
   2   清理空壳条目      需先退出 WorkBuddy
   3   清理并删历史文件  需先退出 WorkBuddy，多省几 MB
   4   清理孤儿历史目录  需先退出 WorkBuddy，清 projects 残留
   5   清理仅元数据目录  需先退出 WorkBuddy，连目录一起删
   6   安全清理缓存      需先退出 WorkBuddy，日志与缓存
   7   深度清理缓存      需先退出 WorkBuddy，会丢回滚
   8   备份数据库        随时可用，随时能跑
   9   查看磁盘占用      随时可用，随时能跑
   10  从备份还原        需先退出 WorkBuddy
   11  导出诊断报告      随时可用，反馈问题用

   --------------------------------------------------------------
   0   退出

   请选择（0 退出）:
```

**它干三件事**：

1. **清空壳** —— 删掉数据库里指向已不存在文件夹的那些记录；
2. **清仅元数据目录** —— 顶层只有 `.workbuddy-ai`（Windows 上是 `.workbuddy`）这类
   隐藏元数据、一个实际文件都没有的工作空间，可选连本地目录一起删；
3. **清缓存** —— 日志和缓存，应用重启会自己重建；也能深度清掉历史回滚数据。

**它不干的事**：不动 WorkBuddy 本体、不动你的文件、不改工作空间内容、
不碰你上传的图片附件（`blobs`）、不碰会话历史（`projects`）、不碰登录态（`app/session`）。

---

## 下载

不想 `git clone` 的话，到 [Releases](https://github.com/Swipa5fox/WorkBuddyCleaner/releases/latest)
下载对应平台的包。**两个平台分开打包**，别下错：

| 平台 | 发布包 | 包里的启动器 | 解压 |
| :--- | :--- | :--- | :--- |
| macOS（Linux 同一份） | `wbclean-1.4-macos.tar.gz` | `install.sh`、`wbclean.command` | `tar -xzf wbclean-1.4-macos.tar.gz` |
| Windows 10 / 11 | `wbclean-1.4-windows.zip` | `install.ps1`、`wbclean.bat` | 右键「全部解压」 |

两个包里的 `bin/wbclean`、`README.md`、`LICENSE` 完全一致，
差别只在启动脚本：`install.sh` / `wbclean.command` 用 LF 换行且带可执行位，
`install.ps1` / `wbclean.bat` 用 CRLF 换行（PowerShell 脚本另存为 UTF-8 with BOM，
否则中文提示在 Windows PowerShell 5.1 下会变乱码）。

> 包里是**脚本**，不是编译好的 exe。两个平台都还需要 Python 3.7+
> （只要标准库，不用 `pip install`）。Windows 上没装 Python 也能跑 ——
> 启动器会退到 WorkBuddy 自带的解释器。

校验下载是否完整：

```bash
# macOS
shasum -a 256 wbclean-1.4-macos.tar.gz

# Windows（PowerShell）
Get-FileHash .\wbclean-1.4-windows.zip -Algorithm SHA256
```

对照 Release 页面里列出的校验值即可。

---

## 免责声明

**请在使用前完整阅读本节。下载、安装或使用本工具，即表示你已知悉并接受以下全部内容。**

### 一、非官方工具

- 本项目是**个人开发的开源工具**，与腾讯公司、WorkBuddy 官方**没有任何关系**，
  未获其授权、认可、赞助或背书。WorkBuddy 及相关标识是其权利人的商标。
- 本工具通过读取 WorkBuddy 的**本地 SQLite 数据库**工作。这属于该软件未公开的实现细节，
  **不是官方提供的接口**。官方任意一次升级都可能改变数据结构导致本工具失效，
  这一点无法避免，也不构成作者的责任。
- 本工具不修改、不重打包、不分发 WorkBuddy 本体，仅在本地读写其数据文件。

### 二、不盈利

- 本项目**完全免费**，不收取任何费用，不含付费功能、订阅制、捐赠入口或任何形式的变现。
- **不含任何广告、推广链接、邀请码、联盟返利。**
- **不含任何遥测、埋点、统计上报。** 工具不联网，不会将你的任何数据发送到任何地方。
  `--report` 生成的诊断报告只输出到你的终端或你显式指定的本地文件。
- 作者不从本项目获取任何直接或间接的商业利益。

### 三、合法使用

- 请仅在**你拥有合法使用权**的设备与数据上使用本工具 —— 通常是你自己电脑上、你自己的 WorkBuddy 数据。
- 请自行确认使用行为符合**你所在地的法律法规**，以及你与 WorkBuddy 之间的**用户协议**。
  修改第三方软件的数据文件可能受其服务条款约束，是否允许请自行判断并承担相应后果。
- 本工具**不提供**任何破解、绕过授权、规避付费、去除功能限制的能力，也**严禁**用于上述目的。
- **严禁**用于未经授权访问他人设备或数据。
- 若你是企业用户，请先确认公司 IT 政策是否允许此类工具。

### 四、风险自负

- 本工具会**修改本地数据库**（删除记录）。虽然每次写操作前都会自动备份，
  但**仍存在数据丢失的可能性**。
- 因使用本工具造成的任何直接或间接损失 —— 包括但不限于数据丢失、软件异常、
  配置损坏、工作中断、设备损坏 —— **作者不承担任何责任**。
- **建议**：首次使用前，自行完整备份数据目录
  （macOS 为 `~/.workbuddy-ai/`，Windows 为 `%USERPROFILE%\.workbuddy\`）。

### 五、无担保

本软件按「现状」（AS IS）提供，不附带任何明示或暗示的担保，包括但不限于对适销性、
特定用途适用性及不侵权的担保。详见 [LICENSE](LICENSE)。

---

## 安装

**环境要求**：Python 3.7 及以上。只用标准库，无需 `pip install`。

两种方式选一种：**下载发布包**（见 [下载](#下载)）解开直接 `install`，
或者 `git clone` 整个仓库。下面的命令都以解压后的目录（或仓库根目录）为当前目录。

### macOS / Linux

```bash
# 解压发布包，或 git clone 后 cd 进去
tar -xzf wbclean-1.4-macos.tar.gz
cd wbclean-1.4-macos

./install.sh
```

默认安装到 `~/.local/bin/wbclean`。装到别处：

```bash
./install.sh /usr/local/bin
```

装完验证：

```bash
wbclean --version
wbclean scan
```

> 如果提示 `command not found: wbclean`，说明 `~/.local/bin` 不在 PATH 里。
> `install.sh` 会打印对应的 `export` 命令，复制执行即可。

**卸载**：删掉 `~/.local/bin/wbclean` 即可。工具不在系统任何其他位置留下文件
（备份目录 `~/WorkBuddy清理备份/` 需手动删除）。

### Windows

先装 Python（[python.org](https://www.python.org/downloads/windows/)，安装时勾上
**Add python.exe to PATH**）。没装也能先跑起来，启动器会退到 WorkBuddy 自带的解释器，
但装一个更省事。

解压 `wbclean-1.4-windows.zip`（或 `git clone` 后进入目录），在该目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

默认装到 `%LOCALAPPDATA%\wbclean`，生成 `wbclean.cmd` 包装器。装到别处：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Prefix D:\tools\wbclean
```

包装器生成后，按脚本提示把该目录加进 PATH（脚本只打印命令，不擅自改系统设置）：

```powershell
$p = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', "$p;$env:LOCALAPPDATA\wbclean", 'User')
```

> 别用 `setx PATH "..."`：超过 1024 字符的 PATH 会被它**截断**，
> 上面的 .NET 写法没有这个坑。改的是「用户变量」，不影响系统级 PATH。

然后**关掉当前窗口重新打开**（PATH 只在启动时读一次），验证：

```powershell
wbclean --version
wbclean scan
```

不想装也行 —— 解压目录里的 `wbclean.bat` 双击就能开菜单：

```
wbclean.bat          →  交互式菜单
```

**卸载**：删掉 `%LOCALAPPDATA%\wbclean` 目录，再从 PATH 里去掉那一项
（备份目录 `%USERPROFILE%\WorkBuddy清理备份\` 需手动删除）。

---

## 用法

### 命令一览

| 命令 | 作用 | 需退出 WorkBuddy |
| :--- | :--- | :---: |
| `wbclean scan` | 列出空壳工作空间、僵尸会话 | 否 |
| `wbclean stats` | 磁盘占用明细 | 否 |
| `wbclean cache` | 查看缓存与日志占用 | 否 |
| `wbclean report` | 生成诊断报告 | 否 |
| `wbclean backup` | 备份数据库 | 否 |
| `wbclean clean` | 清理空壳条目 | **是** |
| `wbclean clean --orphans` | 清理不属于任何工作空间的孤儿历史目录 | **是** |
| `wbclean clean --metadata-only` | 清理仅元数据目录（连本地目录一起删） | **是** |
| `wbclean cache --clean` | 清理缓存与日志 | **是** |
| `wbclean restore` | 从备份还原 | **是** |
| `wbclean menu` | 交互式菜单 | 视所选命令 |

「否」= 只读操作，WorkBuddy 运行中也能安全执行。

### 菜单

```bash
wbclean menu
```

macOS 上也可以双击解压目录里的 `wbclean.command`。
Windows 上双击 `wbclean.bat`（装过的话，`%LOCALAPPDATA%\wbclean\wbclean.cmd` 也行）。

### 常用参数

```bash
# 清理空壳
wbclean clean --dry-run          # 只预览要删什么，不写任何东西
wbclean clean --history          # 同时删除空壳项目的会话历史文件夹
wbclean clean --orphans          # 同时删除孤儿历史目录（见下节）
wbclean clean --force            # 连「疑似离线」的条目一起清（确认目录真删了再用）
wbclean clean --sessions         # 额外清理全部已软删除的会话记录
wbclean clean --yes              # 跳过交互确认（谨慎）

# 清理缓存
wbclean cache                    # 只看占用，不动任何东西
wbclean cache --clean            # 清安全项（日志 + 缓存）
wbclean cache --clean --dry-run  # 预览会删什么
wbclean cache --clean --keep-days 3   # 日志保留最近 3 天（含今天）
wbclean cache --clean --deep     # 连历史回滚数据一起清

# 报告相关
wbclean report                   # 人读的文本报告
wbclean report --format json     # 机器可读，适合贴 issue
wbclean report -o report.json    # 写入文件

# 备份相关
wbclean restore                  # 列出所有备份
wbclean restore 20261029-143022  # 还原到指定备份
```

### 缓存清理：两级，白名单制

`wbclean cache` 走的是**白名单**——只有下面这几个目录会被删，不在这张表里的一律不碰。

**安全清理**（`--clean`）：应用重启会自己重建，删了不心疼。

| 目录 | 内容 | 说明 |
| :--- | :--- | :--- |
| `logs/` | 运行日志、沙箱日志、滚动旧日志 | 通常最大头，几百 MB 起步 |
| `cache/` | 产品配置与会话快照 | 应用会重新拉 |
| `app/cache/` | Electron 渲染进程缓存 | 随便删 |

Windows 上还多一项（Electron 主进程日志另存了一份，不在数据目录里）：

| 目录 | 内容 | 说明 |
| :--- | :--- | :--- |
| `%LOCALAPPDATA%\WorkBuddy\logs\` | 启动器与渲染进程日志 | 随便删 |

**深度清理**（`--clean --deep`）：会丢掉一些历史能力，想清楚再加。

| 目录 | 内容 | 代价 |
| :--- | :--- | :--- |
| `file-history/` | 文件回滚历史 | 以后滚不回改过的文件了 |
| `changes-detail/` | 变更详情 | 历史变更记录看不了 |
| `artifact-index/` | 产物索引 | 产物列表要重建 |

**这些绝对不碰**：

| 目录 | 内容 |
| :--- | :--- |
| `blobs/` | 你上传的图片附件 |
| `projects/` | 会话历史记录 |
| `app/session/` | 登录态与会话状态 |
| `workbuddy.db` | 数据库本体 |
| `~/WorkBuddy AI/` | 你的工作空间文件夹 |

日志支持按天保留。`--keep-days N` 的含义是**保留最近 N 个日历日，含今天**：

- 形如 `2026-10-28` 的日期目录按目录名判断；
- 其他条目（`sandbox/`、`*.old.log`）没有日期可依，按修改时间判断，
  同样以「今天零点往前 N-1 天」为界 —— 否则当天的沙箱日志会被无条件删掉。

`--keep-days 1` 只留今天，`--keep-days 7` 留今天加前 6 天。

```bash
wbclean cache --clean --keep-days 7    # 最近一周的日志留着，方便排障
```

### 自定义数据目录

WorkBuddy 本身没有提供修改数据目录的设置（macOS 固定在 `~/.workbuddy-ai`，
Windows 固定在 `%USERPROFILE%\.workbuddy`）。
如果你把数据放在了别处，可以用参数或环境变量覆盖：

```bash
wbclean --app-home /path/to/.workbuddy-ai scan
WBCLEAN_APP_HOME=/path/to/.workbuddy-ai wbclean scan
```

```powershell
wbclean --app-home D:\backup\.workbuddy scan
$env:WBCLEAN_APP_HOME = "D:\backup\.workbuddy"; wbclean scan
```

优先级：显式 `--db` > `--app-home` / `WBCLEAN_APP_HOME` 推导 > 平台默认。
同时给了 `--app-home` 和 `--db` 时以 `--db` 为准（stderr 会打一行提示），
不会出现「以为读的是这个库、实际读的是那个库」。

---

## Windows 说明

同一份代码，Windows 上有三处必须区别对待的地方。这一节把它们讲清楚，
你遇到「跟 macOS 不一样」的现象时先看这里。

### 数据目录与工作空间根

| 项 | macOS | Windows |
| :--- | :--- | :--- |
| 数据目录 | `~/.workbuddy-ai` | `%USERPROFILE%\.workbuddy` |
| 数据库 | `~/.workbuddy-ai/workbuddy.db` | `%USERPROFILE%\.workbuddy\workbuddy.db` |
| 工作空间根 | `~/WorkBuddy AI` | `%USERPROFILE%\WorkBuddy` |
| 会话历史 | `~/.workbuddy-ai/projects/` | 同左 |
| 备份目录 | `~/WorkBuddy清理备份/` | `%USERPROFILE%\WorkBuddy清理备份\`（用 `--app-home` 时跟着数据目录走） |

数据库表结构两边一致（`workspaces` / `sessions`），所以扫描和清理逻辑通用。

### 一个目录，两种写法

这是 Windows 上最容易踩的坑。WorkBuddy 会把**同一个文件夹**在库里存成两种形式：

```
C:\Users\Administrator\WorkBuddy\2026-08-06-14-46-01     ← 文件系统给的
C:/Users/Administrator/WorkBuddy/2026-08-06-14-46-01     ← 用户输入/命令行给的
```

字符不相等，但指的是同一个目录。如果按字符串精确匹配，会话统计会少一半，
清理也会漏掉一半。本工具在比较前统一做路径归一化（大小写 + 分隔符 + 尾斜杠），
所以两边的会话都能算准、都能删掉。

### 「隐藏」的判定不一样

`--metadata-only` 要判断目录里「有没有实际文件」。隐藏项的判定两边不同：

```
macOS    名字以 . 开头就算隐藏      .workbuddy-ai  ✓
Windows  名字以 . 开头，或带隐藏属性  FILE_ATTRIBUTE_HIDDEN 也算
```

Windows 上隐藏是**文件属性**不是命名约定，所以本工具会真正去读
`st_file_attributes` 的第 2 位，而不是只看名字。读不到属性时按「可见」处理
（宁可多算成有内容，也不少算）。

另外 Windows 的元数据目录名是 `.workbuddy`，不是 `.workbuddy-ai` ——
记忆文件计数两种都探一遍，避免在某个平台上漏数。

### 只读文件会让删除失败

Windows 上被标记只读的文件，`shutil.rmtree` 会抛 `PermissionError`。
本工具用 `onerror` 钩子先去掉只读位再重试，所以「清理仅元数据目录」
在 Windows 上不会因为某个只读文件半途而废。

### projects 目录名的规则不同

会话历史目录名是路径变形来的，两边规则不一样：

```
macOS    /Users/foo/WorkBuddy AI/x      →  Users-foo-WorkBuddy AI-x
Windows  C:\Users\foo\WorkBuddy\x       →  c-Users-foo-WorkBuddy-x
```

Windows 上盘符要转小写，而且 `C:\` 整体只产生**一个** `-`。
沿用 macOS 那套「冒号换 -、分隔符换 -」会算出 `c--Users-foo`（双横线），
跟磁盘上的真实目录名一条都对不上。

### 孤儿历史目录（`--orphans`）

Windows 上真正占空间的是这个：任务删了、工作空间记录也没了，
但 `projects\` 下那份会话历史原样躺着。几百 MB 很常见，
而且这些目录**不会**出现在侧边栏，你根本看不见。

```powershell
wbclean scan                 # 会列出孤儿目录数量和总占用
wbclean clean --orphans --dry-run    # 先看会删什么
wbclean clean --orphans              # 执行
```

判定链条三步，缺一不可：

1. 目录名不在 `workspaces` 表里 —— 不是现役工作空间；
2. 用 `sessions.cwd` 反查它的真实路径，查不到才退回按目录名反解；
3. **真实路径仍然存在** —— 说明只是记录没了、目录你还在用，**不动**。

第 3 步是关键。实测中 43 个"孤儿"里有 7 个对应的目录其实还在
（E 盘两个游戏目录、`~/LightOps` 等，合计 178 MB），一刀切会误删。
工具宁可少删，也不碰还在用的目录。

### 进程检测

macOS 用 `pgrep` + `lsof`，Windows 两个都没有。换成：

- **进程枚举**：直接调 Windows API 查 `WorkBuddy*.exe`，不起 `tasklist` 子进程
  （部分机器上系统工具会被安全策略拦掉，那会变成"检测不到应用在跑"这种最危险的误判）；
- **文件占用**：用共享模式 0 独占打开 `workbuddy.db`，能开说明没人持有句柄。

WorkBuddy 在 Windows 上会常驻托盘，**右键托盘图标 → 退出**，
确认任务管理器里没有 `WorkBuddy.exe` 再执行写命令。

---

## 工作原理

### 扫描逻辑是动态的

工作空间的路径**不写死**在任何地方。流程是这样的：

1. 把 `workspaces` 表里所有记录读出来，每条带着工作空间的绝对路径；
2. 路径先归一化（大小写、斜杠、末尾分隔符），这样 Windows 上同一个目录的
   `C:\...` 和 `C:/...` 两种写法能归到一条记录上；
3. 对每个路径做**三态判定**，而不是简单的「在 / 不在」：

   | 判定 | 依据 | 处理 |
   | :--- | :--- | :--- |
   | 正常 | 目录能访问 | 保留 |
   | 空壳 | 父目录在、自己不在 | 进清理范围 |
   | 疑似离线 | 卷未挂载（`/Volumes/X` 不存在、Windows 盘符没连）、上级目录也缺失、访问报错 | **一律不动** |

   把「外置盘没插」判成「目录被删」是这类工具最容易栽的坑：等盘插回来，
   侧边栏条目已经没了；要是带了 `--history`，会话历史也一起没了。
4. 只有「空壳」进清理范围。「疑似离线」只在输出里提示一下，等你确认目录是真删了，
   再用 `clean --force` 显式覆盖。

所以你就算改过 WorkBuddy 的「默认保存路径」也没关系，新旧工作空间一视同仁。

### 清理时到底删什么

| 对象 | 处理方式 |
| :--- | :--- |
| `workspaces` 表中目录已不存在的记录 | 删除 |
| 这些工作空间下 `deleted_at` 非空的会话记录 | 删除 |
| 目录仍然存在的工作空间记录 | **保留** |
| 目录只是「此刻不可达」的记录（磁盘没挂载、网络盘掉线） | **保留**，只有加 `--force` 才清理 |
| 顶层只有隐藏元数据、无实际文件的工作空间 | 默认**保留**，加 `--metadata-only` 时连本地目录一起删 |
| `deleted_at` 为空的存活会话 | **保留**（结果里会列出提醒） |
| `workspace-display-names.json` 中指向已消失路径的条目 | 删除 |
| `projects` 下不属于任何工作空间、且目标路径已消失的历史目录 | 仅在加 `--orphans` 时删除 |
| 任何本地文件夹 | **不动**（除非显式加 `--history` / `--orphans` / `--metadata-only`） |
| `deleted_at` 为空的会话（除非加 `--sessions`） | **不动** |

### 「仅元数据」怎么判定

目录存在，但**顶层没有任何非隐藏项** —— 只有 `.workbuddy-ai`（Windows 上是
`.workbuddy`）、`.DS_Store` 这类 WorkBuddy 自己生成的元数据。也就是「开过会话、
但没往里放过任何文件」的工作空间，用户视角就是空壳。

隐藏的判定按平台走：

| 平台 | 判定方式 |
| :--- | :--- |
| macOS / Linux | 名字以 `.` 开头 |
| Windows | 名字以 `.` 开头，**或**带隐藏属性（`FILE_ATTRIBUTE_HIDDEN`） |

`--metadata-only` 会删除本地目录，包括其中的 `.workbuddy-ai/memory/*.md`
记忆日志，确认页会逐条列出将删除几个记忆文件。执行前会重新检查一次：
从确认到执行之间如果目录里出现了实际文件，该目录自动跳过。

---

## 安全设计

| 机制 | 说明 |
| :--- | :--- |
| **三态判定** | 只有「父目录在、自己不在」才认定目录已删除；卷未挂载、盘符未连接、上级目录缺失一律归为疑似离线，默认不碰，需 `--force` 才清理 |
| **写操作前强制检查** | 检测 WorkBuddy 进程是否在运行、数据库文件是否被占用，任一命中就中止，绝不与应用抢锁 |
| **自动备份** | 每次写操作前，用 SQLite 在线备份 API 生成一致性快照到 `~/WorkBuddy清理备份/<时间戳>/` |
| **删除清单** | 每次 `clean` 结束后把删掉的每条工作空间、每个历史目录写进备份目录的 `deleted.json`，事后能核对到底动了什么 |
| **事务回滚** | 写操作包在事务里，出错自动 `ROLLBACK`，数据库保持原样 |
| **schema 探测** | 开跑前校验必需的表和字段，对不上就列出缺失项并以退出码 2 退出，不带假设改数据 |
| **路径越界防护** | `--history` / `--orphans` 删除前校验目标路径确实位于数据目录的 `projects/` 之内 |
| **孤儿目录三步判定** | 先排除现役工作空间，再用 `sessions.cwd` 反查真实路径，最后确认该路径已消失；任一条件不满足就保留 |
| **跨平台进程检测** | macOS 用 `pgrep` + `lsof`，Windows 用 Win32 API 枚举进程 + 独占句柄试探；检测不到时宁可中止也不冒险写入 |
| **缓存清理白名单** | 只删代码里写死的固定目录（macOS 6 个、Windows 7 个）；`blobs` / `projects` / `app/session` / 数据库 / 工作空间不在名单内，代码里不存在删它们的路径 |
| **二次路径校验** | 缓存清理逐项删除前，再确认目标路径位于数据目录之内，防止配置被改坏后误删 |
| **只读连接** | `scan` / `stats` / `cache` / `report` / `backup` 使用 SQLite 只读 URI 或不碰数据库，运行中的应用不受影响 |

---

## 兼容性

| 项 | 状态 |
| :--- | :--- |
| macOS | 支持（主要开发与测试平台） |
| Windows | 支持（Windows 10 / 11，进程检测走 Win32 API，无需 `lsof`） |
| Linux | 理论可用，未实测（发布包用 `wbclean-1.4-macos.tar.gz` 那份） |
| Python | 3.7 及以上（CI 覆盖 3.9 与 3.13） |
| 第三方依赖 | 无 |
| 发布包 | `wbclean-1.4-macos.tar.gz` / `wbclean-1.4-windows.zip` |

---

## 版本历史

| 版本 | 主要变化 |
| :--- | :--- |
| **1.4**（2026-11-04） | 识别「仅元数据」工作空间：目录在、但顶层只有 `.workbuddy-ai` 这类隐藏元数据，一个实际文件都没有——旧版只判断「目录在不在」，会把这些一直留在侧边栏。新增 `clean --metadata-only` 连目录一起清，菜单加第 5 项。Windows 侧修了三处：隐藏属性判定（`FILE_ATTRIBUTE_HIDDEN`）、元数据目录名（`.workbuddy`）、只读文件删除（`remove_tree`）。 |
| **1.3**（2026-11-02 重建） | 三处修复：① 疑似离线的条目（外置盘没挂载、网络盘掉线）不再被当成空壳清理，新增 `clean --force` 显式覆盖；② `--keep-days` 改为「含今天的 N 个日历日」，`sandbox/`、`*.old.log` 等非日期条目按 mtime 判断；③ `--db` 不再被 `--app-home` / `WBCLEAN_APP_HOME` 静默覆盖。`--version` 起带构建日期 |
| **1.3** | **支持 Windows**（与 macOS 同一份代码，发布包分开）；新增孤儿历史目录清理 `clean --orphans`；`clean` 结束时写 `deleted.json` 删除清单；备份目录跟随 `--app-home`；菜单扩到 10 项 |
| 1.2 | 新增缓存清理，分安全 / 深度两级，白名单制 |
| 1.1 | 首个公开版本：扫描、清理空壳、备份、还原、诊断报告 |

升级直接覆盖装就行（`install.sh` / `install.ps1` 会先把旧版备份一份）。
数据库结构一直没变，备份可以跨版本还原。

---

## 常见问题

**Q：清理完侧边栏还是老样子？**

A：清的是数据库记录，得重启 WorkBuddy 才会重新读。

**Q：会不会把我文件删了？**

A：清空壳条目的时候不碰任何本地文件夹。

真正会删文件的只有 `--history` 和 `--metadata-only` 两个开关：前者只删「工作空间文件夹
已经不存在」的历史会话目录，后者只删「顶层一个实际文件都没有」的目录，而且执行前
还会再查一遍——要是你在确认之后往里放了东西，那个目录会被跳过。

外置盘没挂载、网络盘掉线的条目会被归到「疑似离线」里跳过，不会因为此刻访问不到
就顺手把条目和历史一起清了。

**Q：删错了还能救回来吗？**

A：能。每次写操作前都会自动备份，`wbclean restore` 列出来挑个时间点还原就行。

备份默认在 `~/WorkBuddy清理备份/`。如果用 `--app-home` 指到别处的数据目录，
备份会跟着放在那个目录同级，不会散落到 home 里。

**Q：为什么非要退出 WorkBuddy？**

A：它运行时握着数据库连接和 WAL 文件。两边同时写有损坏风险，这赌不起，所以工具
宁可停下来让你关掉，也不去抢。

**Q：升级 WorkBuddy 之后报「数据库结构不一致」？**

A：官方改了表或者字段。工具会把缺哪几个列出来然后停下，一个字节都不会改。

把 `wbclean report` 的输出贴到 issue 里就行，我按着缺失项改适配。

**Q：清缓存会不会把正在用的东西搞坏？**

A：`--clean` 只动日志和缓存，应用下次启动自己重建，功能上没影响。

`--deep` 会连文件回滚历史和变更记录一起删——如果你之后还想回滚改过的文件，
别加这个参数。哪一级都不会碰你的图片附件、会话记录和工作空间文件夹。

**Q：日志里有我要排查问题的信息，能只清一部分吗？**

A：能，`--keep-days N` 保留最近 N 个日历日（含今天）。日期目录按目录名判断，
`sandbox/`、`*.old.log` 这种没日期的按修改时间判断：

```bash
wbclean cache --clean --keep-days 7
```

**Q：包下错了怎么办？**

A：看扩展名——`.tar.gz` 是 macOS 的，`.zip` 是 Windows 的。

里面那个 `bin/wbclean` 两份完全一样，区别只在启动脚本的换行符和可执行位。
Windows 上下错成 `.tar.gz`，解出来会是一堆换行符不对的脚本，双击 `install.sh`
当然没反应。

**Q：Windows 上双击 `wbclean.bat`，窗口一闪就没了？**

A：多半是没找到 Python。脚本退出前其实打了错误信息，只是窗口跟着关了看不到。

在 PowerShell 里跑一次看具体报错：

```powershell
python bin\wbclean --version
```

提示找不到 Python 就装一个，安装时记得勾上「Add python.exe to PATH」。

**Q：明明装了 Python，Windows 还说「Python 3.7+ not found」？**

A：商店版 Python 会在 `WindowsApps\python.exe` 放个占位壳，抢先响应 `python` 命令。

先用 `py -3 --version` 确认真解释器在不在；在的话直接 `py -3 bin\wbclean scan` 调。

**Q：侧边栏的条目数跟 `scan` 报的对不上？**

A：`scan` 数的是数据库里的记录，侧边栏可能只显示当前挂着会话的那部分，而且不重启
不刷新。以 `scan` 为准，清完重启再对照。

---

## 反馈问题

遇到问题时，先跑一条命令生成诊断报告，把输出贴到
[Issues](https://github.com/Swipa5fox/WorkBuddyCleaner/issues)：

```bash
wbclean report
```

机器可读格式：

```bash
wbclean report --format json
```

报告包含环境信息、数据库结构匹配情况、空壳与疑似离线条目数量、会话统计和磁盘占用，
**不含任何会话标题或对话内容**。

> ⚠️ 报告里会包含你的数据目录路径（含用户名）。贴之前扫一眼，介意就把那几行删掉。

---

## 许可

[MIT License](LICENSE) © 2026 wbclean contributors

本项目为个人非商业开源项目，不提供任何形式的商业支持或担保。
