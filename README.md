# wbclean

WorkBuddy 工作空间清理工具 —— 清掉侧边栏里那些「本地文件夹已经不存在」的空壳条目。

WorkBuddy 的侧边栏「空间」分组只提供逐条右键「从列表中移除」，没有批量入口。
用得越久，空壳条目越多：它们对应的文件夹早删了，但数据库里的记录还在，
列表就一直堆着。这个工具把这些空壳条目批量清掉，顺带提供诊断、备份、还原和磁盘占用统计。

```
   1  诊断当前状态      随时可用，不用退应用
   2  清理空壳条目      需先退出 WorkBuddy
   3  清理并删历史文件  需先退出 WorkBuddy，多省几 MB
   4  备份数据库        随时可用，随时能跑
   5  查看磁盘占用      随时可用，随时能跑
   6  从备份还原        需先退出 WorkBuddy
   7  导出诊断报告      随时可用，反馈问题用
```

---

## ⚠️ 先读这一段

**本工具直接读写 WorkBuddy 的内部 SQLite 数据库，这是未公开的实现细节，不是官方 API。**

- WorkBuddy 每次升级都可能调整数据库结构。本工具启动时会先校验依赖的表和字段，
  **对不上就明确报错并停止，不会带着不确定的假设去改你的数据**。
- 依赖的具体结构：`workspaces` 表（`path` / `last_opened_at`）、
  `sessions` 表（`cwd` / `deleted_at`）、`workspace-display-names.json` 的格式、
  `~/.workbuddy-ai/projects/` 的目录命名规则（绝对路径的 `/` 换成 `-`）。
- 万一清理出了问题，每个写操作前都会自动备份，可以用 `wbclean restore` 回滚。
- 使用前请先读一遍下面的「工作原理」，确认它的行为符合你的预期。

---

## 安装

需要 **Python 3.7+**（只用标准库，无需 pip install）。

```bash
git clone https://github.com/OWNER/wbclean.git   # 换成实际仓库地址
cd wbclean
./install.sh
```

`install.sh` 默认装到 `~/.local/bin/wbclean`。想换位置：

```bash
./install.sh /usr/local/bin
```

装完确认：

```bash
wbclean --version
wbclean scan
```

> 装完如果提示 `command not found: wbclean`，说明 `~/.local/bin` 不在 PATH 里，
> `install.sh` 会提示你把对应那行加进 `~/.zshrc`。

---

## 用法

### 命令行

| 命令 | 说明 | 需要退出 WorkBuddy |
|---|---|---|
| `wbclean scan` | 列出空壳工作空间、僵尸会话 | 否 |
| `wbclean stats` | 磁盘占用明细 | 否 |
| `wbclean report` | 生成诊断报告 | 否 |
| `wbclean backup` | 备份数据库 | 否 |
| `wbclean clean` | 清理空壳条目 | **是** |
| `wbclean restore` | 从备份还原 | **是** |
| `wbclean menu` | 交互式菜单 | 视所选命令 |

### 菜单

```bash
wbclean menu
```

或者双击仓库根目录的 `wbclean.command`（macOS 会用 Terminal 打开菜单）。

### 常用参数

```bash
wbclean clean --dry-run          # 只预览要删什么，不写任何东西
wbclean clean --history          # 同时删除空壳项目的会话历史文件夹
wbclean clean --sessions         # 额外清理全部已软删除的会话记录
wbclean clean --yes              # 跳过交互确认（谨慎）

wbclean report --format json     # 机器可读的报告，适合贴 issue
wbclean report -o report.json    # 写到文件

wbclean restore                  # 列出可用备份
wbclean restore 20261029-143022  # 还原到某个备份
```

### 自定义数据目录

WorkBuddy 没有提供修改数据目录的设置（它固定在 `~/.workbuddy-ai`）。
如果你把数据放在了别处，可以用参数或环境变量覆盖：

```bash
wbclean --app-home /path/to/.workbuddy-ai scan
WBCLEAN_APP_HOME=/path/to/.workbuddy-ai wbclean scan
```

---

## 工作原理

### 扫描逻辑是动态的

不硬编码任何具体的工作空间路径。做法是：

1. 读 `workspaces` 表的全部记录，每条记录里存着工作空间的绝对路径；
2. 对每个路径用 `os.path.isdir()` **实时判断文件夹现在还在不在**；
3. 文件夹已消失 → 空壳；还在 → 保留。

所以你改了 WorkBuddy 的「默认保存路径」也不影响它，新旧工作空间一视同仁。

### 清理时删什么

| 对象 | 处理方式 |
|---|---|
| `workspaces` 表中目录已不存在的记录 | 删除 |
| 这些工作空间下 `deleted_at` 非空的会话记录 | 删除 |
| 目录仍在的工作空间记录 | **保留** |
| `deleted_at` 为空的存活会话 | **保留**（会列出提醒） |
| `workspace-display-names.json` 中指向已消失路径的条目 | 删除 |
| 任何本地文件夹 | **不动**（除非显式加 `--history`） |
| `deleted_at` 为空的会话（除非加 `--sessions`） | **不动** |

### 安全设计

- **写操作前强制检查**：检测 WorkBuddy 进程是否还在运行、数据库文件是否被占用，
  任一命中就中止，绝不与运行中的应用抢锁。
- **每次写操作前自动备份**：数据库用 SQLite 在线备份 API 生成一致性快照，
  存到 `~/WorkBuddy清理备份/<时间戳>/`。
- **失败自动回滚**：写操作包在事务里，出错就 `ROLLBACK`。
- **schema 探测**：开跑前校验必需的表和字段，对不上就报出缺失项并以退出码 2 退出。
- **路径越界防护**：`--history` 删除历史文件夹前，校验目标路径确实位于
  `~/.workbuddy-ai/projects/` 之内。
- **只读命令用 SQLite 只读 URI 连接**：`scan` / `stats` / `report` / `backup`
  在 WorkBuddy 运行时也能安全执行，不影响正常使用。

---

## 反馈问题

遇到问题时，先跑一条命令生成诊断报告，把输出贴到 issue 里：

```bash
wbclean report
```

JSON 格式更适合自动化：

```bash
wbclean report --format json
```

报告里包含环境信息、数据库结构匹配情况、空壳条目数量、会话统计和磁盘占用，
**不含任何会话标题或对话内容**。注意报告里会有你的数据目录路径（含用户名），
贴之前扫一眼，介意就把那几行删掉。

---

## 兼容性

| 项 | 状态 |
|---|---|
| macOS | 支持（主要开发和测试平台） |
| Linux | 理论可用，未实测（`WorkBuddy` 本身是桌面应用，Linux 上一般没有数据可清） |
| Windows | **暂不支持**（缺启动器，且进程占用检测依赖 `lsof`） |
| Python | 3.7 及以上 |
| 第三方依赖 | 无 |

---

## 常见问题

**清理后侧边栏还是那样？**
清的是数据库里的记录，需要重启 WorkBuddy 才会刷新。

**会不会删掉我的文件？**
清理空壳条目时不动任何本地文件夹。唯一会删文件的是 `--history`，
它只删「工作空间文件夹已经不存在」的那些历史会话目录。

**能恢复吗？**
可以。每个写操作前都会自动备份，用 `wbclean restore` 选时间戳还原。
备份默认在 `~/WorkBuddy清理备份/`，删之前记得看一眼。

**为什么必须退出 WorkBuddy？**
WorkBuddy 运行时会持有数据库连接和 WAL。并发写入有损坏风险，
所以工具宁可停下来让你退出，也不冒这个险。

---

## License

MIT，见 [LICENSE](LICENSE)。
