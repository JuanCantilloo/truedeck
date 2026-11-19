#!/usr/bin/env python3
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
VENV_PYTHON = os.path.join(BACKEND_DIR, "venv", "bin", "python")
PORT = int(os.getenv("TRUDECK_PORT", "8050"))
ENABLE_RELOAD = os.getenv("TRUDECK_RELOAD", "0").strip().lower() in {"1", "true", "yes", "on"}

if not os.path.exists(VENV_PYTHON):
    print("Virtual environment not found. Using system python3...")
    VENV_PYTHON = sys.executable

cmd = [
    VENV_PYTHON, "-m", "uvicorn", "main:app",
    "--app-dir", BACKEND_DIR,
    "--host", "0.0.0.0",
    "--port", str(PORT),
]

if ENABLE_RELOAD:
    cmd.append("--reload")

print("==================================================")
print("🚀 Iniciando Servidor TrueDeck Telemetría & Mapas")
print(f"📍 Abre en tu navegador: http://localhost:{PORT}")
print(f"⚙️  Modo: {'desarrollo (reload)' if ENABLE_RELOAD else 'producción'}")
print("==================================================")

try:
    subprocess.run(cmd, check=False)
except KeyboardInterrupt:
    print("\nServidor detenido.")
