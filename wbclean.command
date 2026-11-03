#!/bin/bash
# wbclean 双击启动器（macOS）
#
# 双击本文件会用 Terminal 打开交互式菜单。
# 菜单渲染交给 wbclean menu（Python 按显示宽度排版，中文才对得齐）。

cd "$(dirname "$0")" || exit 1

if command -v wbclean >/dev/null 2>&1; then
    WBCLEAN=$(command -v wbclean)
elif [ -x "./bin/wbclean" ]; then
    WBCLEAN="./bin/wbclean"
elif [ -x "$HOME/.local/bin/wbclean" ]; then
    WBCLEAN="$HOME/.local/bin/wbclean"
else
    echo ""
    echo "  [错误] 找不到 wbclean。"
    echo "  先运行 ./install.sh 安装，或直接执行 ./bin/wbclean menu"
    echo ""
    read -r -n 1 -s -p "  按任意键关闭..."
    exit 1
fi

# ---------------------------------------------------------------
# 判断是「双击 .command」还是「在已有终端里执行」
#
# 双击时父进程是终端模拟器本身，脚本结束 = 那个窗口的 shell 结束；
# 在已有终端里跑时父进程是 zsh/bash，脚本结束只是回到原 shell。
# 两种情况下「按任意键关闭窗口」的含义不同，不能一概而论。
# ---------------------------------------------------------------
parent_comm=$(/bin/ps -o comm= -p "$PPID" 2>/dev/null)
case "$parent_comm" in
    *Terminal*|*iTerm*|*Warp*|*Hyper*|*kitty*|*Alacritty*|*WezTerm*)
        launched_by_window=1
        ;;
    "")
        # ps 不可用，退回 SHLVL 判断：
        # 双击时终端直接执行本脚本，SHLVL 为 1；
        # 在 zsh/bash 里再跑一层，SHLVL 至少为 2。
        if [ "${SHLVL:-1}" -le 1 ]; then
            launched_by_window=1
        else
            launched_by_window=0
        fi
        ;;
    *)
        launched_by_window=0
        ;;
esac

clear
"$WBCLEAN" menu
menu_rc=$?

echo ""

if [ "$launched_by_window" = "1" ]; then
    read -r -n 1 -s -p "  按任意键关闭窗口..."
    echo ""
    # 尝试主动关窗口。终端若未授予自动化权限会失败（macOS 报 -10004），
    # 这里静默忽略 —— 窗口去留最终由终端的偏好设置决定。
    osascript -e 'tell application "Terminal" to close front window' >/dev/null 2>&1
fi

exit "$menu_rc"
