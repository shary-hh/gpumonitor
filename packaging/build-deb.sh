#!/usr/bin/env bash
# Construye el paquete .deb y el tarball de código fuente en dist/.
#
#   ./packaging/build-deb.sh
#
# Variables opcionales:
#   VERSION=1.0.0
#   MAINTAINER="Nombre <correo>"
#   HOMEPAGE="https://github.com/usuario/gpumonitor"
set -euo pipefail
umask 022

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="gpumonitor"
VERSION="${VERSION:-1.0.0}"
ARCH="all"
MAINTAINER="${MAINTAINER:-shary-hh <193357000+shary-hh@users.noreply.github.com>}"
HOMEPAGE="${HOMEPAGE:-https://github.com/shary-hh/gpumonitor}"
BUILD="$ROOT/build/${PKG}_${VERSION}_${ARCH}"
DIST="$ROOT/dist"

rm -rf "$BUILD"
mkdir -p \
    "$BUILD/DEBIAN" \
    "$BUILD/usr/bin" \
    "$BUILD/usr/lib/$PKG" \
    "$BUILD/usr/share/applications" \
    "$BUILD/usr/share/icons/hicolor/scalable/apps" \
    "$BUILD/usr/share/doc/$PKG/docs" \
    "$BUILD/usr/share/man/man1"

install -m 755 "$ROOT/gpumonitor.py" "$BUILD/usr/lib/$PKG/gpumonitor.py"
install -m 644 "$ROOT/gpumonitor.svg" \
    "$BUILD/usr/share/icons/hicolor/scalable/apps/gpumonitor.svg"
install -m 644 "$ROOT/README.md" "$BUILD/usr/share/doc/$PKG/README.md"
install -m 644 "$ROOT/packaging/copyright" "$BUILD/usr/share/doc/$PKG/copyright"
install -m 644 "$ROOT/docs/screenshot.png" "$BUILD/usr/share/doc/$PKG/docs/screenshot.png"
install -m 644 "$ROOT/docs/panel.png" "$BUILD/usr/share/doc/$PKG/docs/panel.png"

cat > "$BUILD/usr/bin/gpumonitor" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/gpumonitor/gpumonitor.py "$@"
EOF
chmod 755 "$BUILD/usr/bin/gpumonitor"

cat > "$BUILD/usr/share/applications/gpumonitor.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=GPUMonitor (UHD 630)
GenericName=GPU monitor
Comment=Temperatura, frecuencia y RAM de la iGPU Intel UHD Graphics 630
Exec=gpumonitor
Icon=gpumonitor
Terminal=false
Categories=System;Monitor;
Keywords=gpu;temperatura;intel;uhd;630;monitor;ram;
StartupNotify=true
EOF

sed -e "s/@VERSION@/$VERSION/g" -e "s/@DATE@/$(date +%Y-%m-%d)/g" \
    "$ROOT/packaging/gpumonitor.1" > "$BUILD/usr/share/man/man1/gpumonitor.1"
gzip -9n "$BUILD/usr/share/man/man1/gpumonitor.1"

cat > "$BUILD/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: $MAINTAINER
Installed-Size: $(du -sk "$BUILD/usr" | cut -f1)
Depends: python3, python3-gi, gir1.2-gtk-3.0, gir1.2-pango-1.0, python3-cairo, gir1.2-ayatanaappindicator3-0.1
Section: utils
Priority: optional
Homepage: $HOMEPAGE
Description: Monitor de temperatura y RAM para la iGPU Intel UHD Graphics 630
 Ventana GTK3, icono de bandeja y modo CLI para vigilar la temperatura
 de la iGPU Intel UHD Graphics 630, su frecuencia y actividad, y el uso
 de memoria RAM. Los colores se adaptan al tema activo de Cinnamon/GTK.
 .
 En Linux la UHD 630 no expone un sensor térmico propio; la app usa el
 paquete de la CPU (misma oblea) como aproximación y lo indica claramente.
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst"

cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postrm"

mkdir -p "$DIST"
dpkg-deb --build --root-owner-group "$BUILD" \
    "$DIST/${PKG}_${VERSION}_${ARCH}.deb"

# Tarball de código fuente listo para ./install.sh
STAGE="$ROOT/build/${PKG}-${VERSION}"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$ROOT/gpumonitor.py" "$ROOT/gpumonitor.svg" "$ROOT/install.sh" \
      "$ROOT/README.md" "$ROOT/LICENSE" "$STAGE/"
cp -a "$ROOT/docs" "$ROOT/packaging" "$STAGE/"
if [ -d "$ROOT/.github" ]; then
    cp -a "$ROOT/.github" "$STAGE/"
fi
chmod -R u=rwX,go=rX "$STAGE"
tar -czf "$DIST/${PKG}-${VERSION}.tar.gz" -C "$ROOT/build" "${PKG}-${VERSION}"

cd "$DIST"
sha256sum "${PKG}_${VERSION}_${ARCH}.deb" "${PKG}-${VERSION}.tar.gz" > SHA256SUMS

echo
echo "Paquetes generados en $DIST:"
ls -lh "${PKG}_${VERSION}_${ARCH}.deb" "${PKG}-${VERSION}.tar.gz" SHA256SUMS
echo
echo "Instalar con:  sudo apt install ./${PKG}_${VERSION}_${ARCH}.deb"
