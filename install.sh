#!/bin/bash
# wbclean 一键安装
#
#   ./install.sh              装到 ~/.local/bin/wbclean
#   ./install.sh /usr/local/bin  装到指定目录
#
# 只用标准库，不需要 pip install。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/bin/wbclean"
PREFIX="${1:-$HOME/.local/bin}"
TARGET="$PREFIX/wbclean"

echo ""
echo "  ===================================================="
echo "    wbclean 安装程序"
echo "  ===================================================="
echo ""

# ---- 前置检查
if [ "$(uname -s)" != "Darwin" ] && [ "$(uname -s)" != "Linux" ]; then
    echo "  [错误] 只支持 macOS 和 Linux，当前系统是 $(uname -s)。"
    echo "         Windows 支持正在开发中。"
    echo ""
    exit 1
fi

PY=""
for cand in python3 /usr/bin/python3 /usr/local/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' 2>/dev/null; then
            PY="$(command -v "$cand")"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "  [错误] 没找到 Python 3.7 或更高版本。"
    echo "         macOS: brew install python   或  python3.org 下载安装"
    echo "         Debian/Ubuntu: sudo apt install python3"
    echo ""
    exit 1
fi
echo "  Python    $($PY --version 2>&1)  ($PY)"

if [ ! -f "$SRC" ]; then
    echo "  [错误] 找不到主脚本：$SRC"
    echo ""
    exit 1
fi

# ---- 安装
mkdir -p "$PREFIX"

if [ -f "$TARGET" ]; then
    BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"
    cp "$TARGET" "$BACKUP"
    echo "  已备份旧版本 → $BACKUP"
fi

cp "$SRC" "$TARGET"
chmod +x "$TARGET"
echo "  安装完成  → $TARGET"

# ---- PATH 检查
case ":$PATH:" in
    *":$PREFIX:"*)
        echo "  PATH      已包含 $PREFIX"
        ;;
    *)
        echo ""
        echo "  [注意] $PREFIX 不在 PATH 里，装完还要加一行："
        echo ""
        echo "      echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
        echo "      source ~/.zshrc"
        echo ""
        echo "  （bash 用户把 .zshrc 换成 .bashrc）"
        ;;
esac

echo ""
echo "  验证："
echo "    $TARGET --version"
echo "    $TARGET scan"
echo ""
