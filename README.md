# GPUMonitor — Intel UHD Graphics 630

Miniaplicación para **Linux Mint 22.3 (Cinnamon)** que muestra en tiempo real la
temperatura de la iGPU **Intel UHD Graphics 630** (Coffee Lake GT2, driver
`i915`), junto con su frecuencia, actividad y el uso de memoria RAM. Incluye
ventana GTK3, icono en la bandeja del sistema y modo terminal.

![Captura de GPUMonitor](docs/screenshot.png)

En el panel de Cinnamon el icono muestra temperatura y RAM etiquetadas
(`38° GPU | 33% RAM`), sin necesidad de abrir la ventana:

![Icono de bandeja](docs/panel.png)

```
┌────────────────────────────────────────┐
│  Intel UHD Graphics 630                │
│  i915 · Coffee Lake GT2                │
│                                        │
│              38 °C                     │
│             Normal                     │
│  Aproximación: paquete de la CPU       │
│                                        │
│  Fuente           Paquete CPU · oblea  │
│  CPU (paquete)              38.0 °C    │
│  Chipset PCH                41.0 °C    │
│  Memoria RAM       9.2 / 15.5 GB · 59% │
│  Frecuencia GPU         350 / 1100 MHz │
│  Actividad GPU                   12 %  │
│  ▁▂▁▂▃▂▁▂▁▂▃▂▁▂▁▂▃▂▁▂▁▂▃▂▁▂▁▂▃▂       │
└────────────────────────────────────────┘
```

## Aviso importante sobre la temperatura

**La UHD 630 no expone un sensor de temperatura propio en Linux.** No existe
ningún `hwmon` del driver `i915` ni una zona térmica `gpu` en:

```
/sys/class/drm/card1/device/hwmon/...   ← no existe en esta iGPU
```

La GPU está integrada en la misma oblea que la CPU, así que la app usa como
**aproximación** la temperatura del **paquete de la CPU** (`coretemp`,
`Package id 0`, o `x86_pkg_temp`) y lo marca con `≈` en el modo CLI y con el
texto «Aproximación» en la ventana. Esto es lo máximo que el hardware permite
leer sin herramientas privilegiadas.

> En tu panel de Cinnamon aparece `GPU: NaN °C` por el applet
> `gputemperature@silentage.com`. Ese `NaN` es exactamente el mismo motivo: no
> hay sensor que leer. Puedes desactivar ese applet y usar GPUMonitor, que sí
> muestra un valor útil y además frecuencia/actividad reales.

Si algún día el kernel expone un sensor propio (`hwmon` llamado `i915`/`xe`,
`hwmon` del dispositivo DRM o una `thermal_zone` con «gpu» en el nombre), la
aplicación lo detecta automáticamente y deja de usar la aproximación.

## Características

- Ventana GTK3 con temperatura grande, estado por colores y mini-gráfica.
- Icono de bandeja que **dibuja la temperatura y la RAM dentro del icono** con
  etiquetas y números grandes (`39° GPU | 33% RAM`), visible en Cinnamon aunque
  el panel no muestre etiquetas de AppIndicator.
- **Colores tomados del tema activo** de Cinnamon/GTK: acento para la GPU,
  acento claro para la RAM, texto del panel para las etiquetas y colores de
  aviso/error para los estados altos.
- Frecuencia real de la GPU y frecuencia máxima (RP0).
- Actividad de la GPU calculada con la residencia **RC6** del `i915`.
- Uso de **memoria RAM y swap** desde `/proc/meminfo`.
- Temperaturas de contexto: paquete de CPU y chipset PCH.
- Modo CLI y salida JSON para scripts.
- Sin `sudo`, sin demonios y sin dependencias pesadas.

## Requisitos

Linux Mint 22.3 / Ubuntu 24.04 con Python 3 y GTK3. Comprueba/instala:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-cairo \
                 gir1.2-ayatanaappindicator3-0.1
```

Todo lo que se lee está en `sysfs` y es legible por tu usuario.

## Descarga e instalación

- **Repositorio:** https://github.com/shary-hh/gpumonitor
- **Releases (.deb y tar.gz):** https://github.com/shary-hh/gpumonitor/releases

### Paquete .deb (recomendado)

```bash
sudo apt install ./gpumonitor_1.0.0_all.deb
```

Instala la aplicación para todos los usuarios, con lanzador, icono y página de
manual (`man gpumonitor`). El `.deb` se publica en la sección *Releases* del
repositorio.

### Desde el código (solo tu usuario)

```bash
tar xzf gpumonitor-1.0.0.tar.gz
cd gpumonitor-1.0.0
chmod +x install.sh gpumonitor.py
./install.sh
```

Esto instala:

| Elemento | Ruta |
|---|---|
| Aplicación | `~/.local/share/gpumonitor/gpumonitor.py` |
| Icono | `~/.local/share/icons/hicolor/scalable/apps/gpumonitor.svg` |
| Lanzador | `~/.local/share/applications/gpumonitor.desktop` |
| Comando | `~/.local/bin/gpumonitor` |

Arranca al iniciar sesión (opcional):

```bash
./install.sh --autostart
```

Desinstalar:

```bash
./install.sh --uninstall
```

Para generar tú mismo el `.deb` y el tarball de release:

```bash
./packaging/build-deb.sh
```

Los paquetes quedan en `dist/` junto con `SHA256SUMS`.

Puedes personalizar el mantenedor y la URL del paquete:

```bash
MAINTAINER="Tu Nombre <tu@correo>" \
HOMEPAGE="https://github.com/shary-hh/gpumonitor" \
./packaging/build-deb.sh
```

## Uso

Desde el menú de aplicaciones: **GPUMonitor (UHD 630)**.

```bash
gpumonitor                 # ventana + bandeja
gpumonitor --no-tray       # solo ventana
gpumonitor --cli           # terminal, refresco continuo
gpumonitor --cli --once    # una lectura
gpumonitor --json          # una muestra JSON (para scripts)
gpumonitor --interval 0.5  # intervalo personalizado
```

Salida del modo CLI:

```
≈ GPU  38.0 °C  |  350 MHz / 1100 MHz  | act  12 %  | CPU  38.0 °C  | PCH  41.0 °C  | RAM  9.2/15.5 GB 59%
```

El símbolo `≈` indica que la temperatura es la aproximación del paquete de CPU.
Al cerrar la ventana con la bandeja activa, la app se oculta y sigue midiendo;
usa **Salir** en el menú del icono para terminarla.

## Tamaño en el panel

Cinnamon limita la altura de los iconos de la bandeja con el ajuste
`panel-zone-icon-sizes`. Para que el icono de GPUMonitor se vea grande se ha
subido la zona derecha a **32 px** (por defecto suele estar en 24):

```bash
gsettings set org.cinnamon panel-zone-icon-sizes \
  '[{"panelId": 1, "left": 0, "center": 0, "right": 32}]'
```

El icono de GPUMonitor es ancho (`39° GPU | 33% RAM`) y aprovecha toda la altura
del panel. Este ajuste afecta a todos los iconos de la zona derecha (escudo,
red, volumen); para volver al tamaño original:

```bash
gsettings set org.cinnamon panel-zone-icon-sizes \
  '[{"panelId": 1, "left": 0, "center": 0, "right": 24}]'
```

## Colores

La app lee el tema activo; no usa una paleta fija:

| Elemento | Origen |
|---|---|
| Texto del panel | `#panel { color: ... }` de `cinnamon.css` |
| Acento de la GPU | `selection-background-color` del tema Cinnamon |
| RAM normal | acento aclarado un 45 % hacia blanco |
| Aviso / error | `warning_color` / `error_color` del tema GTK |

Se revisa cada 30 s, así que al cambiar de tema el icono se adapta solo. Con
`Mint-Y-Dark-Aqua`: `#1f9ede` (GPU), `#84caed` (RAM), `#f27835` (aviso),
`#fc4138` (error) y `#e1e1e1` (texto del panel).

## Qué mide exactamente

| Dato | Origen en `sysfs` |
|---|---|
| Tarjeta Intel | `/sys/class/drm/card*/device/vendor` = `0x8086` |
| Temp. GPU real (si existe) | `hwmon/*/temp*_input` o `thermal_zone*/temp` |
| Aproximación | `coretemp` → `temp1_input` (`Package id 0`) / `x86_pkg_temp` |
| Chipset PCH | `hwmon` con nombre `pch_*` → `temp1_input` |
| Frecuencia GPU | `gt/gt0/rps_act_freq_mhz` |
| Frecuencia máxima | `gt/gt0/rps_RP0_freq_mhz` |
| Actividad GPU | Δ de `gt/gt0/rc6_residency_ms` respecto al tiempo real |
| Memoria RAM | `/proc/meminfo` → `MemTotal - MemAvailable` |
| Swap | `/proc/meminfo` → `SwapTotal - SwapFree` |
| CPU paquete | `coretemp` `Package id 0` |

La actividad es el porcentaje de tiempo que la GPU está **fuera** de RC6. No es
el uso de un motor concreto (render/vídeo), sino cuánto está despierta la GT;
es la métrica más fiable disponible sin `perf` ni `intel_gpu_top`.

## Solución de problemas

- **No aparece el icono en la bandeja**: en Cinnamon puede quedar en la zona
  oculta de iconos (la flecha `^` del panel). Comprueba que tienes
  `gir1.2-ayatanaappindicator3-0.1`. También puedes usar `--no-tray`.
- **El icono no actualiza el número**: mata instancias antiguas con
  `pkill -f "python3 .*gpumonitor.py"` y vuelve a abrir.
- **`GPU: NaN °C` en el panel**: es el applet antiguo
  `gputemperature@silentage.com`; desactívalo desde *Configuración del panel →
  Applets*. GPUMonitor no necesita ese applet.
- **Quiero ver errores**: lanza `gpumonitor` desde una terminal.
- **Temperaturas altas**: la iGPU comparte disipación con la CPU. Si el paquete
  pasa de ~80 °C de forma sostenida, revisa ventilación y polvo del equipo.

## Estructura del proyecto

```
gpumonitor/
├── gpumonitor.py          # aplicación (GUI, bandeja y CLI)
├── gpumonitor.svg         # icono
├── install.sh             # instalador/desinstalador por usuario
├── LICENSE                # MIT
├── README.md
├── docs/
│   ├── screenshot.png
│   └── panel.png
├── packaging/
│   ├── build-deb.sh       # genera .deb + tar.gz en dist/
│   ├── copyright
│   └── gpumonitor.1       # página de manual
├── share/
│   ├── ANUNCIO-es.md      # borrador para foro/Reddit
│   └── ANNOUNCEMENT-en.md
└── .github/workflows/
    ├── build.yml          # compila el .deb en cada push
    └── release.yml        # adjunta .deb y tar.gz al crear un tag
```

## Publicar y compartir

### GitHub

Repositorio: https://github.com/shary-hh/gpumonitor

Para publicar una nueva release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

El workflow `.github/workflows/release.yml` construye el `.deb`, el tarball y
`SHA256SUMS`, y los adjunta a la release de GitHub.

### Comunidad de Linux Mint

- **Foro** → *Software & Applications*: usa `share/ANUNCIO-es.md`.
- **Reddit** → r/linuxmint: usa `share/ANNOUNCEMENT-en.md`.
- **Linux Mint Community** → *Tutorials*: publica una guía con las capturas.
- **Cinnamon Spices** solo acepta applets, desklets, extensiones y temas; esta
  aplicación de bandeja no entra en ese catálogo. Si quieres aparecer allí,
  habría que hacer una versión applet.

## Licencia

MIT © 2026 shary-hh. Consulta [LICENSE](LICENSE).

## Nota técnica

En esta máquina (Mint 22.3, kernel 7.0.0-43, i915, `8086:3e92`) el único
sensor térmico relacionado con la GPU es el paquete de la CPU. Por eso el valor
principal es una **estimación honesta y etiquetada**, no una lectura inventada:
la app nunca presenta el dato como si fuera un sensor dedicado de la GPU.
