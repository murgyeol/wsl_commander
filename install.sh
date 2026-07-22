#!/bin/bash
# WSL Commander One-Liner Installer script
# Usage: curl -sSL https://raw.githubusercontent.com/murgyeol/wsl_commander/main/install.sh | bash

set -e

INSTALL_DIR="$HOME/.wsl_commander"
BIN_DIR="$HOME/.local/bin"

echo "🚀 WSL Commander 설치를 시작합니다..."

# 1. 기존 디렉토리 확인 및 최신 코드 다운로드
if [ -d "$INSTALL_DIR" ]; then
    echo "🔄 기존 설치 디렉토리($INSTALL_DIR)를 업데이트합니다..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    echo "📥 GitHub에서 WSL Commander 코드 다운로드 중..."
    git clone https://github.com/murgyeol/wsl_commander.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 2. 실행 권한 부여
chmod +x "$INSTALL_DIR/lwc"
chmod +x "$INSTALL_DIR/lcom"
chmod +x "$INSTALL_DIR/wsl_commander.py"

# 3. 심볼릭 링크 등록 (~/.local/bin/lwc)
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/lwc" "$BIN_DIR/lwc"

echo ""
echo "🎉 WSL Commander가 성공적으로 설치되었습니다!"
echo "--------------------------------------------------"
echo "💡 어떤 디렉토리에서든 다음 명령어로 실행할 수 있습니다:"
echo "   $ lwc"
echo "--------------------------------------------------"

# PATH 안내
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "⚠️  참고: $BIN_DIR 경로가 PATH에 포함되어 있지 않습니다."
    echo "   ~/.bashrc 또는 ~/.zshrc 에 아래 문장을 추가해 주세요:"
    echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
