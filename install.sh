#!/usr/bin/env bash
# Instalador local de GPUMonitor (sin root).
#
#   ./install.sh              instala app + lanzador + comando `gpumonitor`
#   ./install.sh --autostart  además la arranca al iniciar sesión
#   ./install.sh --uninstall  desinstala todo
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.local/share/gpumonitor"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin"
AUTOSTART="$HOME/.config/autostart"
DESKTOP="$APPS/gpumonitor.desktop"
PYTHON="/usr/bin/python3"

uninstall() {
    rm -rf "$DEST"
    rm -f "$APPS/gpumonitor.desktop" "$DESKTOP"
    rm -f "$ICONS/gpumonitor.svg"
    rm -f "$BIN/gpumonitor"
    rm -f "$AUTOSTART/gpumonitor.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$APPS" >/dev/null 2>&1 || true
    echo "GPUMonitor desinstalado."
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

if [[ ! -f "$SRC/gpumonitor.py" || ! -f "$SRC/gpumonitor.svg" ]]; then
    echo "Error: ejecuta este script desde la carpeta del proyecto." >&2
    exit 1
fi

mkdir -p "$DEST" "$APPS" "$ICONS" "$BIN"
install -m 755 "$SRC/gpumonitor.py" "$DEST/gpumonitor.py"
install -m 644 "$SRC/gpumonitor.svg" "$ICONS/gpumonitor.svg"

cat > "$BIN/gpumonitor" <<EOF
#!/bin/sh
exec "$PYTHON" "$DEST/gpumonitor.py" "\$@"
EOF
chmod 755 "$BIN/gpumonitor"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=GPUMonitor (UHD 630)
GenericName=Monitor de GPU
Comment=Temperatura, frecuencia y actividad de la iGPU Intel UHD Graphics 630
Exec="$PYTHON" "$DEST/gpumonitor.py"
Icon=$ICONS/gpumonitor.svg
Terminal=false
Categories=System;Monitor;
Keywords=gpu;temperatura;intel;uhd;630;monitor;
StartupNotify=true
EOF

if [[ "${1:-}" == "--autostart" ]]; then
    mkdir -p "$AUTOSTART"
    cat > "$AUTOSTART/gpumonitor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GPUMonitor
Comment=Monitor de temperatura de la iGPU Intel UHD Graphics 630
Exec="$PYTHON" "$DEST/gpumonitor.py"
Icon=$ICONS/gpumonitor.svg
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF
    echo "Autostart activado."
fi

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "Instalado en: $DEST"
echo "Lanzador:    $DESKTOP"
echo "Comando:     gpumonitor  (o $BIN/gpumonitor)"
echo
echo "Abre 'GPUMonitor (UHD 630)' desde el menú, o ejecuta: gpumonitor"
