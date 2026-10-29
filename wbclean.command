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

clear
"$WBCLEAN" menu

echo ""
read -r -n 1 -s -p "  按任意键关闭窗口..."
echo ""
