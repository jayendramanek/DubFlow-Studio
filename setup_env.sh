#!/usr/bin/env bash
# ==============================================================================
# DubFlow Studio - Universal Environment Setup (Linux Cloud VMs & macOS)
# ==============================================================================
set -e

OS_TYPE="$(uname -s)"
echo "🚀 Initializing DubFlow Studio setup on $OS_TYPE..."

# 1. Install FFmpeg dynamically based on host OS
if ! command -v ffmpeg &> /dev/null; then
    echo "📦 Installing FFmpeg..."
    if [ "$OS_TYPE" = "Darwin" ]; then
        if command -v brew &> /dev/null; then
            brew install ffmpeg
        else
            echo "⚠️ Homebrew not detected on macOS. Please install brew or ffmpeg."
        fi
    elif [ "$OS_TYPE" = "Linux" ]; then
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y ffmpeg python3-venv python3-pip
        elif command -v yum &> /dev/null; then
            sudo yum install -y ffmpeg
        else
            echo "⚠️ Package manager not recognized. Please install ffmpeg manually."
        fi
    fi
else
    echo "✅ FFmpeg is already installed ($(ffmpeg -version | head -n 1 | cut -d' ' -f3))"
fi

# 2. Select Python executable
PYTHON_BIN="python3"
if command -v python3.11 &> /dev/null; then
    PYTHON_BIN="python3.11"
fi

# 3. Create virtual environment
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📁 Creating virtual environment at ./$VENV_DIR using $PYTHON_BIN..."
    $PYTHON_BIN -m venv "$VENV_DIR"
fi

echo "🔄 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 4. Upgrade pip & build tools
echo "⬆️ Upgrading pip, wheel, setuptools..."
pip install --upgrade pip setuptools wheel

# 5. Install PyTorch
echo "📦 Installing PyTorch (auto-configures for CUDA / MPS / CPU)..."
pip install torch torchaudio

# 6. Install requirements
echo "📦 Installing pipeline dependencies from requirements.txt..."
pip install -r requirements.txt

echo ""
echo "======================================================================"
echo "🎉 Setup complete! DubFlow Studio is ready."
echo "======================================================================"
echo "To start the FastAPI REST API Server & Admin Panel:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo "   # or: uvicorn api:app --host 0.0.0.0 --port 3333"
echo "======================================================================"
