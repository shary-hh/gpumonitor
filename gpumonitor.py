#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
GPUMonitor - miniaplicación para vigilar la iGPU Intel UHD Graphics 630.

Qué hace
--------
* Muestra la temperatura de la GPU en una ventana GTK3 y en la bandeja del
  sistema (AppIndicator), con intervalo configurable.
* Muestra también frecuencia real, actividad (residencia RC6), temperaturas
  de contexto (paquete de CPU y chipset PCH) y memoria RAM usada.
* Configuración persistente: intervalo, umbrales, etiquetas, colores del tema,
  swap, cierre a bandeja y arranque automático.
* Los colores del icono se leen del tema activo de Cinnamon/GTK (acento, texto
  del panel y avisos), así que se adaptan al cambiar de tema.
* Detecta automáticamente un sensor térmico real de la GPU si el kernel lo
  expone (hwmon "i915"/"xe" o thermal_zone "gpu").

Nota importante sobre la UHD 630
--------------------------------
En Linux esta iGPU *no* publica su propia temperatura: no existe
/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input ni una zona térmica "gpu".
El die de la GPU comparte encapsulado con la CPU, por lo que se usa como
aproximación la temperatura del paquete de la CPU (coretemp / x86_pkg_temp).
La app lo indica en pantalla y en el modo CLI con el símbolo ≈.

Uso
---
    ./gpumonitor.py              # ventana + bandeja
    ./gpumonitor.py --no-tray    # solo ventana
    ./gpumonitor.py --settings   # ventana + configuración
    ./gpumonitor.py --cli        # texto en terminal, refresco continuo
    ./gpumonitor.py --cli --once # una sola lectura
    ./gpumonitor.py --json       # una lectura en JSON (para scripts)
"""

import argparse
import glob
import json
import math
import os
import re
import sys
import tempfile
import time

APP_NAME = "GPUMonitor"
APP_ID = "gpumonitor"
VERSION = "1.1.0"
REFRESH_MS = 1500


# --------------------------------------------------------------------------
# Lectura de sysfs
# --------------------------------------------------------------------------
def _read(path):
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _read_float(path):
    value = _read(path)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_temp(path):
    """Devuelve grados Celsius a partir de un temp*_input en miligrados."""
    value = _read_float(path)
    return None if value is None else value / 1000.0


def _hwmons():
    """Lista de (nombre, ruta) de todos los hwmon del sistema."""
    result = []
    for path in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = _read(os.path.join(path, "name")) or "?"
        result.append((name, path))
    return result


def _intel_card():
    """Ruta /sys/class/drm/cardN de la GPU Intel, o None."""
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        vendor = (_read(os.path.join(card, "device/vendor")) or "").lower()
        if vendor == "0x8086":
            return card
    return None


def _find_gpu_temp():
    """
    Busca un sensor térmico *real* de la GPU.

    Devuelve (ruta, descripción) o None. En la UHD 630 de este equipo no
    existe, pero se deja preparado para otros kernels/equipos.
    """
    # 1) hwmon colgado del dispositivo DRM de la GPU Intel
    card = _intel_card()
    cards = [card] if card else sorted(glob.glob("/sys/class/drm/card[0-9]*"))
    for card_path in cards:
        for path in sorted(glob.glob(card_path + "/device/hwmon/hwmon*/temp*_input")):
            return path, "sensor de la GPU (hwmon del dispositivo DRM)"

    # 2) hwmon cuyo nombre delata a la GPU
    gpu_names = {"i915", "xe", "intel_gpu", "intel-gpu", "gpu"}
    for name, base in _hwmons():
        if name.lower() in gpu_names:
            paths = sorted(glob.glob(base + "/temp*_input"))
            if paths:
                return paths[0], f"sensor de la GPU (hwmon {name})"

    # 3) zona térmica dedicada
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        kind = (_read(os.path.join(zone, "type")) or "").lower()
        if "gpu" in kind or "i915" in kind:
            return os.path.join(zone, "temp"), f"sensor de la GPU ({kind})"

    return None


def _find_package_temp():
    """Temperatura del paquete de la CPU: (ruta, etiqueta) o None."""
    for name, base in _hwmons():
        if name != "coretemp":
            continue
        paths = sorted(glob.glob(base + "/temp*_input"))
        for path in paths:
            label = _read(path.replace("_input", "_label")) or ""
            if label.lower().startswith("package"):
                return path, label
        if paths:
            return paths[0], "coretemp"

    # Alternativa: zona térmica x86_pkg_temp (suele estar en milésimas)
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        kind = (_read(os.path.join(zone, "type")) or "").lower()
        if kind in ("x86_pkg_temp", "cpu-thermal", "soc_thermal"):
            return os.path.join(zone, "temp"), kind

    # Último recurso: el primer sensor disponible
    for name, base in _hwmons():
        paths = sorted(glob.glob(base + "/temp*_input"))
        if paths:
            return paths[0], name
    return None


def _find_pch_temp():
    """Temperatura del chipset PCH (contexto), o None."""
    for name, base in _hwmons():
        if name.lower().startswith("pch"):
            path = os.path.join(base, "temp1_input")
            if os.path.exists(path):
                return path, "PCH"
    return None


def _find_rc6(card):
    """Ruta de rc6_residency_ms de la GPU, o None."""
    if not card:
        return None
    candidates = [os.path.join(card, "gt/gt0/rc6_residency_ms")]
    candidates += sorted(glob.glob(os.path.join(card, "gt/gt*/rc6_residency_ms")))
    candidates += [os.path.join(card, "power/rc6_residency_ms")]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _first_existing(paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


# --------------------------------------------------------------------------
# Memoria RAM
# --------------------------------------------------------------------------
def read_memory():
    """
    Lee /proc/meminfo y devuelve RAM y swap en GB (GiB) y porcentaje usado.

    'Usada' = MemTotal - MemAvailable, el criterio habitual en monitores
    modernos (incluye caché reclamable como disponible, no como ocupada).
    """
    empty = {
        "ram_total_gb": None,
        "ram_used_gb": None,
        "ram_percent": None,
        "swap_total_gb": None,
        "swap_used_gb": None,
    }
    raw = _read("/proc/meminfo")
    if not raw:
        return empty

    info = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            info[key] = int(parts[0])  # valor en kB

    total = info.get("MemTotal")
    if not total:
        return empty

    available = info.get("MemAvailable")
    if available is None:
        available = sum(info.get(k, 0) for k in ("MemFree", "Buffers", "Cached"))
    used = max(0, total - available)

    swap_total = info.get("SwapTotal", 0)
    swap_used = max(0, swap_total - info.get("SwapFree", 0))

    scale = 1024.0 * 1024.0  # kB -> GiB
    return {
        "ram_total_gb": total / scale,
        "ram_used_gb": used / scale,
        "ram_percent": used * 100.0 / total,
        "swap_total_gb": swap_total / scale,
        "swap_used_gb": swap_used / scale,
    }


def icon_path():
    """Localiza el icono SVG junto al script o en la instalación local."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "gpumonitor.svg"),
        os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/gpumonitor.svg"),
        "/usr/share/icons/hicolor/scalable/apps/gpumonitor.svg",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


# --------------------------------------------------------------------------
# Configuración persistente
# --------------------------------------------------------------------------
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "gpumonitor",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "autostart",
    "gpumonitor.desktop",
)

DEFAULT_CONFIG = {
    "refresh_seconds": 1.5,
    "temp_warn": 60,
    "temp_hot": 80,
    "ram_warn": 75,
    "ram_hot": 90,
    "use_theme_colors": True,
    "show_labels": True,
    "show_swap": True,
    "hide_on_close": True,
}


def _cfg_bool(value, default):
    return value if isinstance(value, bool) else default


def _cfg_number(value, default, low, high, cast=float):
    try:
        number = cast(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _normalize_config(raw):
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return cfg
    cfg["refresh_seconds"] = round(
        _cfg_number(
            raw.get("refresh_seconds"),
            DEFAULT_CONFIG["refresh_seconds"],
            0.5,
            10.0,
        ),
        1,
    )
    cfg["temp_warn"] = int(
        _cfg_number(raw.get("temp_warn"), DEFAULT_CONFIG["temp_warn"], 30, 100, int)
    )
    cfg["temp_hot"] = int(
        _cfg_number(raw.get("temp_hot"), DEFAULT_CONFIG["temp_hot"], 31, 110, int)
    )
    cfg["ram_warn"] = int(
        _cfg_number(raw.get("ram_warn"), DEFAULT_CONFIG["ram_warn"], 50, 100, int)
    )
    cfg["ram_hot"] = int(
        _cfg_number(raw.get("ram_hot"), DEFAULT_CONFIG["ram_hot"], 51, 100, int)
    )
    if cfg["temp_hot"] <= cfg["temp_warn"]:
        cfg["temp_hot"] = min(110, cfg["temp_warn"] + 1)
    if cfg["ram_hot"] <= cfg["ram_warn"]:
        cfg["ram_hot"] = min(100, cfg["ram_warn"] + 1)
    for key in ("use_theme_colors", "show_labels", "show_swap", "hide_on_close"):
        cfg[key] = _cfg_bool(raw.get(key), DEFAULT_CONFIG[key])
    return cfg


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return _normalize_config(json.load(fh))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_normalize_config(config), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except OSError as exc:
        print(f"No se pudo guardar la configuración: {exc}", file=sys.stderr)


def autostart_enabled():
    return os.path.exists(AUTOSTART_PATH)


def _desktop_quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_autostart(enabled):
    if not enabled:
        try:
            os.remove(AUTOSTART_PATH)
        except FileNotFoundError:
            pass
        return

    os.makedirs(os.path.dirname(AUTOSTART_PATH), exist_ok=True)
    python = sys.executable or "/usr/bin/python3"
    script = os.path.abspath(__file__)
    icon = icon_path() or "gpumonitor"
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=GPUMonitor\n"
        "Comment=Monitor de temperatura de la iGPU Intel UHD Graphics 630\n"
        f"Exec={_desktop_quote(python)} {_desktop_quote(script)}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-GNOME-Autostart-Delay=5\n"
    )
    with open(AUTOSTART_PATH, "w", encoding="utf-8") as fh:
        fh.write(content)


# --------------------------------------------------------------------------
# Lector de sensores
# --------------------------------------------------------------------------
class GpuReader:
    """Reúne en una muestra todo lo que el kernel permite leer de la iGPU."""

    def __init__(self):
        self.card = None
        self.gpu_temp_path = None
        self.gpu_desc = None
        self.pkg_path = None
        self.pkg_label = None
        self.pch_path = None
        self.rc6_path = None
        self.freq_path = None
        self.freq_max_path = None
        self._prev_rc6 = None
        self._prev_time = None
        self.rediscover()

    def rediscover(self):
        self.card = _intel_card()
        real = _find_gpu_temp()
        if real:
            self.gpu_temp_path, self.gpu_desc = real
        else:
            self.gpu_temp_path, self.gpu_desc = None, None

        pkg = _find_package_temp()
        if pkg:
            self.pkg_path, self.pkg_label = pkg
        else:
            self.pkg_path, self.pkg_label = None, None

        pch = _find_pch_temp()
        self.pch_path = pch[0] if pch else None
        self.rc6_path = _find_rc6(self.card)

        if self.card:
            self.freq_path = _first_existing([
                os.path.join(self.card, "gt/gt0/rps_act_freq_mhz"),
                os.path.join(self.card, "gt_act_freq_mhz"),
            ])
            self.freq_max_path = _first_existing([
                os.path.join(self.card, "gt/gt0/rps_RP0_freq_mhz"),
                os.path.join(self.card, "gt_max_freq_mhz"),
            ])
        else:
            self.freq_path = self.freq_max_path = None

    @property
    def real_sensor(self):
        return self.gpu_temp_path is not None

    def _read_any_temp(self):
        value = _read_temp(self.gpu_temp_path) if self.gpu_temp_path else None
        if value is not None:
            return value
        if self.pkg_path:
            value = _read_temp(self.pkg_path)
            if value is not None:
                return value
        # último recurso: cualquier hwmon
        for _, base in _hwmons():
            paths = sorted(glob.glob(base + "/temp*_input"))
            if paths:
                value = _read_temp(paths[0])
                if value is not None:
                    return value
        return None

    def _activity(self):
        """% de GPU activa a partir de la residencia RC6 entre muestras."""
        if not self.rc6_path:
            return None
        residency = _read_float(self.rc6_path)
        if residency is None:
            return None
        now = time.monotonic() * 1000.0
        activity = None
        if self._prev_rc6 is not None and self._prev_time is not None:
            elapsed = now - self._prev_time
            if elapsed > 0:
                busy_ratio = 1.0 - (residency - self._prev_rc6) / elapsed
                activity = max(0.0, min(100.0, busy_ratio * 100.0))
        self._prev_rc6 = residency
        self._prev_time = now
        return activity

    def sample(self):
        gpu_temp = self._read_any_temp()
        pkg = _read_temp(self.pkg_path) if self.pkg_path else None
        pch = _read_temp(self.pch_path) if self.pch_path else None
        freq = _read_float(self.freq_path) if self.freq_path else None
        freq_max = _read_float(self.freq_max_path) if self.freq_max_path else None
        activity = self._activity()

        if self.real_sensor:
            source = self.gpu_desc
            approx = False
        elif pkg is not None:
            source = "Paquete CPU · misma oblea"
            approx = True
        else:
            source = "sensor genérico del sistema"
            approx = True

        data = {
            "gpu_temp": gpu_temp,
            "approx": approx,
            "source": source,
            "cpu_pkg": pkg,
            "pch": pch,
            "freq": freq,
            "freq_max": freq_max,
            "activity": activity,
            "timestamp": time.time(),
        }
        data.update(read_memory())
        return data


# --------------------------------------------------------------------------
# Modo CLI
# --------------------------------------------------------------------------
def _fmt(value, unit="", digits=0):
    if value is None:
        return "—"
    return f"{value:.{digits}f}{unit}"


def run_cli(reader, interval, once):
    if not reader.real_sensor:
        print(
            "Nota: la UHD 630 no expone sensor térmico propio en Linux; "
            "se muestra el paquete de la CPU (misma oblea) como aproximación.",
            file=sys.stderr,
        )
    try:
        while True:
            data = reader.sample()
            mark = "≈" if data["approx"] else " "
            if data["ram_percent"] is None:
                ram_text = "—"
            else:
                ram_text = (
                    f"{data['ram_used_gb']:.1f}/"
                    f"{data['ram_total_gb']:.1f} GB "
                    f"{data['ram_percent']:.0f}%"
                )
            line = (
                f"{mark} GPU {_fmt(data['gpu_temp'], ' °C', 1):>7}  "
                f"| {_fmt(data['freq'], ' MHz'):>9} / {_fmt(data['freq_max'], ' MHz'):>9}  "
                f"| act {_fmt(data['activity'], ' %', 0):>4}  "
                f"| CPU {_fmt(data['cpu_pkg'], ' °C', 1):>6}  "
                f"| PCH {_fmt(data['pch'], ' °C', 1):>6}  "
                f"| RAM {ram_text:>18}"
            )
            print(line, flush=True)
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0


def run_json(reader):
    print(json.dumps(reader.sample(), ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------
# Interfaz GTK
# --------------------------------------------------------------------------
CSS = b"""
.main-window { background-color: #16161b; }
.gear-button { color: #e5e7eb; }
.gear-button:hover { background-color: #2a2a33; border-radius: 4px; }
.header-title { color: #e5e7eb; font-weight: bold; font-size: 14px; }
.header-sub { color: #8b8b97; font-size: 11px; }
.big-temp { font-weight: 800; }
.status { font-weight: bold; font-size: 13px; }
.note { color: #8b8b97; font-size: 11px; }
.key { color: #9ca3af; font-size: 12px; }
.val { color: #e5e7eb; font-size: 12px; font-weight: bold; }
.footer { color: #6b7280; font-size: 10px; }
separator { background-color: #2a2a33; }
"""

COLOR_OK = "#4ade80"
COLOR_WARN = "#fbbf24"
COLOR_HOT = "#f87171"
COLOR_NA = "#9ca3af"
COLOR_RAM = "#60a5fa"


def _color_for(temp, palette=None, warn=60, hot=80):
    palette = palette or DEFAULT_PALETTE
    if temp is None:
        return palette["fg"], "Sin datos"
    if temp >= hot:
        return palette["error"], "Caliente"
    if temp >= warn:
        return palette["warning"], "Templado"
    return palette["accent"], "Normal"


def _rgb(hex_color):
    return (
        int(hex_color[1:3], 16) / 255.0,
        int(hex_color[3:5], 16) / 255.0,
        int(hex_color[5:7], 16) / 255.0,
    )


def _rounded_rect(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


# --------------------------------------------------------------------------
# Colores del tema de Cinnamon
# --------------------------------------------------------------------------
DEFAULT_PALETTE = {
    "accent": "#1f9ede",
    "accent_light": "#84caed",
    "fg": "#e1e1e1",
    "warning": "#f27835",
    "error": "#fc4138",
}

_DEFINE_RE = re.compile(r"@define-color\s+([A-Za-z0-9_-]+)\s+([^;]+);")
_PANEL_BLOCK_RE = re.compile(r"#panel\s*\{([^}]*)\}", re.S)
_PANEL_COLOR_RE = re.compile(r"(?:^|[\s;])color\s*:\s*([^;]+);", re.M)
_SELECTION_RE = re.compile(r"selection-background-color\s*:\s*([^;]+);")
_RGB_RE = re.compile(r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)")


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _parse_color(value):
    """Convierte '#rgb', '#rrggbb', 'rgb(...)' o 'rgba(...)' a '#rrggbb'."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) >= 6:
            try:
                int(raw[:6], 16)
            except ValueError:
                return None
            return "#" + raw[:6].lower()
    match = _RGB_RE.match(value)
    if match:
        try:
            r, g, b = (
                max(0, min(255, int(float(part)))) for part in match.groups()
            )
        except ValueError:
            return None
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _lighten(hex_color, amount):
    r, g, b = _rgb(hex_color)
    return "#%02x%02x%02x" % (
        int(round((r + (1.0 - r) * amount) * 255)),
        int(round((g + (1.0 - g) * amount) * 255)),
        int(round((b + (1.0 - b) * amount) * 255)),
    )


def _gsettings_string(schema, key):
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        return Gio.Settings.new(schema).get_string(key)
    except Exception:
        return None


def _theme_dirs(name):
    if not name:
        return []
    return [
        os.path.expanduser(f"~/.themes/{name}"),
        os.path.expanduser(f"~/.local/share/themes/{name}"),
        f"/usr/share/themes/{name}",
    ]


def load_theme_palette():
    """
    Lee los colores del tema activo de Cinnamon/GTK.

    - Texto del panel: bloque `#panel` de cinnamon.css.
    - Acento y colores de aviso/error: @define-color del tema GTK.
    - Acento claro para la RAM: aclarado del acento del tema.

    Si algo no se encuentra, se usan los valores de Mint-Y-Dark-Aqua.
    """
    palette = dict(DEFAULT_PALETTE)

    cinnamon_theme = _gsettings_string("org.cinnamon.theme", "name") or ""
    gtk_theme = (
        _gsettings_string("org.cinnamon.desktop.interface", "gtk-theme")
        or _gsettings_string("org.gnome.desktop.interface", "gtk-theme")
        or ""
    )

    # Color de texto y acento del panel (Cinnamon usa St, no el tema GTK)
    accent_from_cinnamon = False
    for base in _theme_dirs(cinnamon_theme):
        text = _read_text(os.path.join(base, "cinnamon", "cinnamon.css"))
        if not text:
            continue
        selection = _SELECTION_RE.search(text)
        if selection:
            accent = _parse_color(selection.group(1))
            if accent:
                palette["accent"] = accent
                accent_from_cinnamon = True
        block = _PANEL_BLOCK_RE.search(text)
        if not block:
            continue
        match = _PANEL_COLOR_RE.search(block.group(1))
        if match:
            color = _parse_color(match.group(1))
            if color:
                palette["fg"] = color
                break

    # Acento, aviso y error del tema GTK
    for base in _theme_dirs(gtk_theme):
        found = False
        for rel in ("gtk-3.0/gtk.css", "gtk-3.0/gtk-dark.css"):
            text = _read_text(os.path.join(base, rel))
            if not text:
                continue
            found = True
            defines = {
                name: value.strip()
                for name, value in _DEFINE_RE.findall(text)
            }
            accent = _parse_color(defines.get("theme_selected_bg_color"))
            if accent and not accent_from_cinnamon:
                palette["accent"] = accent
            warning = _parse_color(defines.get("warning_color"))
            if warning:
                palette["warning"] = warning
            error = _parse_color(defines.get("error_color"))
            if error:
                palette["error"] = error
        if found:
            break

    palette["accent_light"] = _lighten(palette["accent"], 0.45)
    return palette


def make_tray_icon(path, temp, color, ram_percent=None, ram_color=None, palette=None,
                   show_labels=True):
    """
    Dibuja temperatura y (opcionalmente) RAM dentro del icono de bandeja.

    Los colores salen del tema activo: acento para la GPU, acento claro para la
    RAM, texto del panel para las etiquetas y aviso/error para los estados
    altos. El fondo es una tarjeta translúcida derivada del color de texto,
    para integrarse en paneles claros u oscuros.

    Con `show_labels=False` el icono se compacta: mantiene los números grandes
    pero ocupa menos ancho en el panel.
    """
    import cairo
    import gi

    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo

    palette = palette or DEFAULT_PALETTE
    ram_color = ram_color or palette["accent_light"]
    fg_rgb = _rgb(palette["fg"])
    label_rgb = fg_rgb
    has_ram = ram_percent is not None
    compact = has_ram and not show_labels
    width = 180 if compact else (288 if has_ram else 64)
    height = 64

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)

    def draw_text(text, font_size, rgb, cx, cy):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(
            Pango.FontDescription(f"Sans Bold {font_size}")
        )
        layout.set_text(text, -1)
        text_w, text_h = layout.get_pixel_size()
        cr.move_to(cx - text_w / 2.0, cy - text_h / 2.0)
        cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 1.0)
        PangoCairo.show_layout(cr, layout)

    # tarjeta translúcida derivada del color de texto del tema
    _rounded_rect(cr, 2, 2, width - 4, height - 4, 8 if has_ram else 14)
    cr.set_source_rgba(fg_rgb[0], fg_rgb[1], fg_rgb[2], 0.07)
    cr.fill_preserve()
    cr.set_source_rgba(fg_rgb[0], fg_rgb[1], fg_rgb[2], 0.16)
    cr.set_line_width(1.5)
    cr.stroke()

    temp_rgb = _rgb(color)
    ram_rgb = _rgb(ram_color)

    # barras inferiores de estado (finas, para no quitar altura al texto)
    if has_ram:
        if compact:
            _rounded_rect(cr, 8, height - 5, 74, 2.5, 1.25)
            cr.set_source_rgba(*temp_rgb, 0.95)
            cr.fill()
            _rounded_rect(cr, 98, height - 5, 70, 2.5, 1.25)
            cr.set_source_rgba(*ram_rgb, 0.95)
            cr.fill()
            divider_x = 90
        else:
            _rounded_rect(cr, 8, height - 5, 118, 2.5, 1.25)
            cr.set_source_rgba(*temp_rgb, 0.95)
            cr.fill()
            _rounded_rect(cr, 142, height - 5, 130, 2.5, 1.25)
            cr.set_source_rgba(*ram_rgb, 0.95)
            cr.fill()
            divider_x = 131

        cr.move_to(divider_x, 10)
        cr.line_to(divider_x, 54)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.30)
        cr.set_line_width(2.0)
        cr.stroke()
    else:
        _rounded_rect(cr, 10, height - 12, 44, 5, 2.5)
        cr.set_source_rgba(*temp_rgb, 0.95)
        cr.fill()

    # temperatura (bloque izquierdo)
    temp_text = f"{temp:.0f}" if temp is not None else "--"
    if len(temp_text) <= 2:
        temp_font = 43 if has_ram else 30
    else:
        temp_font = 30 if has_ram else 22
    temp_cx = 36 if compact else (33 if has_ram else 32)
    draw_text(temp_text, temp_font, temp_rgb, temp_cx, 30 if has_ram else 28)

    # símbolo de grado
    degree_x = 68 if compact else (67 if has_ram else 53)
    degree_y = 13 if has_ram else 12
    degree_r = 4.5 if has_ram else 3.8
    cr.new_sub_path()
    cr.arc(degree_x, degree_y, degree_r, 0, 2 * math.pi)
    cr.set_source_rgba(*temp_rgb, 0.95)
    cr.set_line_width(1.8)
    cr.stroke()

    # RAM y, opcionalmente, etiquetas GPU/RAM
    if has_ram:
        ram_text = f"{ram_percent:.0f}"
        ram_font = 43 if len(ram_text) <= 2 else 30
        if compact:
            draw_text(ram_text, ram_font, ram_rgb, 126, 30)
            percent_cx, percent_cy = 160, 40
        else:
            draw_text("GPU", 19, label_rgb, 98, 31)
            draw_text(ram_text, ram_font, ram_rgb, 168, 30)
            percent_cx, percent_cy = 203, 40

        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription("Sans Bold 18"))
        layout.set_text("%", -1)
        percent_w, percent_h = layout.get_pixel_size()
        cr.move_to(percent_cx - percent_w / 2.0, percent_cy - percent_h / 2.0)
        cr.set_source_rgba(*ram_rgb, 0.95)
        PangoCairo.show_layout(cr, layout)

        if show_labels:
            draw_text("RAM", 19, label_rgb, 246, 31)

    surface.write_to_png(path)


class MonitorApp:
    MAX_HISTORY = 120

    def __init__(self, reader, use_tray=True, open_settings=False):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib, Gdk

        self.Gtk = Gtk
        self.GLib = GLib
        self.reader = reader
        self.palette = load_theme_palette()
        self.config = load_config()
        self.history = []
        self.ticks = 0
        self.indicator = None
        self.last_data = None
        self.active_palette = self.palette
        self.settings_dialog = None
        self._settings_widgets = None
        self._settings_updating = False
        self._timeout_id = None

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.win = Gtk.Window(title=f"{APP_NAME} — Intel UHD Graphics 630")
        self.win.get_style_context().add_class("main-window")
        self.win.set_default_size(380, 392)
        self.win.set_resizable(False)
        self.win.set_border_width(16)
        self.win.connect("delete-event", self._on_delete)
        ico = icon_path()
        if ico:
            try:
                self.win.set_icon_from_file(ico)
            except Exception:
                pass

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.win.add(box)

        # Cabecera
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        if ico:
            try:
                image = Gtk.Image.new_from_file(ico)
                image.set_pixel_size(30)
                header.pack_start(image, False, False, 0)
            except Exception:
                pass
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label="Intel UHD Graphics 630", xalign=0)
        title.get_style_context().add_class("header-title")
        subtitle = Gtk.Label(label="i915 · Coffee Lake GT2", xalign=0)
        subtitle.get_style_context().add_class("header-sub")
        titles.pack_start(title, False, False, 0)
        titles.pack_start(subtitle, False, False, 0)
        header.pack_start(titles, True, True, 0)

        settings_button = Gtk.Button()
        settings_button.set_relief(Gtk.ReliefStyle.NONE)
        settings_button.set_tooltip_text("Configuración")
        settings_button.set_can_focus(False)
        settings_button.get_style_context().add_class("gear-button")
        settings_button.set_image(
            Gtk.Image.new_from_icon_name(
                "emblem-system-symbolic", Gtk.IconSize.BUTTON
            )
        )
        settings_button.connect("clicked", lambda *_: self._open_settings())
        header.pack_end(settings_button, False, False, 0)
        box.pack_start(header, False, False, 0)

        # Temperatura grande
        self.big = Gtk.Label(xalign=0.5)
        self.big.get_style_context().add_class("big-temp")
        self.big.set_tooltip_text(
            "Temperatura de la iGPU. En la UHD 630 se aproxima con el paquete "
            "de la CPU porque comparten la misma oblea y Linux no expone un "
            "sensor propio de la GPU."
        )
        box.pack_start(self.big, False, False, 4)

        self.status = Gtk.Label(xalign=0.5)
        self.status.get_style_context().add_class("status")
        box.pack_start(self.status, False, False, 0)

        self.note = Gtk.Label(xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
        self.note.get_style_context().add_class("note")
        box.pack_start(self.note, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 4)

        # Rejilla de detalles
        grid = Gtk.Grid(column_spacing=16, row_spacing=4)
        self.detail_values = {}
        rows = [
            ("source", "Fuente"),
            ("cpu_pkg", "CPU (paquete)"),
            ("pch", "Chipset PCH"),
            ("ram", "Memoria RAM"),
            ("freq", "Frecuencia GPU"),
            ("activity", "Actividad GPU"),
        ]
        for index, (key, text) in enumerate(rows):
            key_label = Gtk.Label(label=text, xalign=0)
            key_label.get_style_context().add_class("key")
            value_label = Gtk.Label(label="—", xalign=1)
            value_label.get_style_context().add_class("val")
            value_label.set_hexpand(True)
            grid.attach(key_label, 0, index, 1, 1)
            grid.attach(value_label, 1, index, 1, 1)
            self.detail_values[key] = value_label
        box.pack_start(grid, False, False, 4)

        # Mini gráfica
        self.spark = Gtk.DrawingArea()
        self.spark.set_size_request(-1, 54)
        self.spark.connect("draw", self._draw_spark)
        box.pack_start(self.spark, False, False, 2)

        self.footer = Gtk.Label(xalign=0.5)
        self.footer.get_style_context().add_class("footer")
        box.pack_start(self.footer, False, False, 0)

        if use_tray:
            self._setup_tray()

        self.win.show_all()
        self._tick()
        self._reschedule_timer()
        if open_settings:
            GLib.idle_add(self._open_settings)

    # -- bandeja -----------------------------------------------------------
    def _setup_tray(self):
        indicator_cls = None
        try:
            import gi
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as indicator_cls
        except Exception:
            try:
                import gi
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as indicator_cls
            except Exception:
                self.indicator = None
                return

        ico = icon_path() or "utilities-system-monitor"
        self.indicator = indicator_cls.Indicator.new(
            APP_ID, ico, indicator_cls.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(indicator_cls.IndicatorStatus.ACTIVE)
        self.indicator.set_title(APP_NAME)

        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self._tray_dir = os.path.join(runtime, "gpumonitor")
        try:
            os.makedirs(self._tray_dir, exist_ok=True)
        except OSError:
            self._tray_dir = tempfile.gettempdir()
        self._tray_flip = False

        menu = self.Gtk.Menu()
        show_item = self.Gtk.MenuItem(label="Mostrar monitor")
        show_item.connect("activate", lambda *_: self._show())
        settings_item = self.Gtk.MenuItem(label="Configuración…")
        settings_item.connect("activate", lambda *_: self._open_settings_from_tray())
        quit_item = self.Gtk.MenuItem(label="Salir")
        quit_item.connect("activate", lambda *_: self._quit())
        menu.append(show_item)
        menu.append(settings_item)
        menu.append(self.Gtk.SeparatorMenuItem())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

    # -- configuración -----------------------------------------------------
    def _open_settings_from_tray(self):
        self._show()
        self._open_settings()

    def _active_palette(self):
        palette = dict(self.palette)
        if not self.config.get("use_theme_colors", True):
            palette.update(
                {
                    "accent": COLOR_OK,
                    "accent_light": COLOR_RAM,
                    "warning": COLOR_WARN,
                    "error": COLOR_HOT,
                }
            )
        return palette

    def _reschedule_timer(self):
        if self._timeout_id is not None:
            try:
                self.GLib.source_remove(self._timeout_id)
            except Exception:
                pass
            self._timeout_id = None
        interval = max(0.5, min(10.0, float(self.config["refresh_seconds"])))
        self._timeout_id = self.GLib.timeout_add(
            int(round(interval * 1000)), self._tick
        )

    def _rerender(self):
        if self.last_data is not None:
            self._render(self.last_data)

    def _on_settings_destroyed(self, *_):
        self.settings_dialog = None
        self._settings_widgets = None

    def _open_settings(self):
        Gtk = self.Gtk
        if self.settings_dialog is not None:
            self.settings_dialog.present()
            return

        dialog = Gtk.Dialog()
        dialog.set_title("Configuración — GPUMonitor")
        dialog.set_transient_for(self.win)
        dialog.set_modal(True)
        dialog.set_resizable(False)
        dialog.set_default_size(480, 610)
        dialog.add_button("Restablecer valores", Gtk.ResponseType.APPLY)
        dialog.add_button("Cerrar", Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_border_width(18)
        content.set_spacing(8)

        def section(text):
            label = Gtk.Label(xalign=0)
            label.set_markup(f"<b>{text}</b>")
            label.set_margin_top(6)
            return label

        def row(text, control):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            label = Gtk.Label(label=text, xalign=0)
            label.set_hexpand(True)
            line.pack_start(label, True, True, 0)
            line.pack_end(control, False, False, 0)
            return line

        def spin(value, lower, upper, step, digits=0):
            widget = Gtk.SpinButton.new_with_range(lower, upper, step)
            widget.set_digits(digits)
            widget.set_value(value)
            widget.set_numeric(True)
            widget.set_halign(Gtk.Align.END)
            return widget

        def switch(active):
            widget = Gtk.Switch()
            widget.set_active(active)
            widget.set_halign(Gtk.Align.END)
            return widget

        cfg = self.config
        interval = spin(cfg["refresh_seconds"], 0.5, 10.0, 0.5, 1)
        temp_warn = spin(cfg["temp_warn"], 30, 100, 1)
        temp_hot = spin(cfg["temp_hot"], 31, 110, 1)
        ram_warn = spin(cfg["ram_warn"], 50, 100, 1)
        ram_hot = spin(cfg["ram_hot"], 51, 100, 1)
        theme_switch = switch(cfg["use_theme_colors"])
        labels_switch = switch(cfg["show_labels"])
        swap_switch = switch(cfg["show_swap"])
        close_switch = switch(cfg["hide_on_close"])
        autostart_switch = switch(autostart_enabled())

        content.pack_start(section("Actualización"), False, False, 0)
        content.pack_start(
            row("Intervalo de refresco (segundos)", interval), False, False, 0
        )
        content.pack_start(Gtk.Separator(), False, False, 4)

        content.pack_start(section("Umbrales"), False, False, 0)
        content.pack_start(
            row("Temperatura templada (°C)", temp_warn), False, False, 0
        )
        content.pack_start(
            row("Temperatura crítica (°C)", temp_hot), False, False, 0
        )
        content.pack_start(row("RAM alta (%)", ram_warn), False, False, 0)
        content.pack_start(row("RAM crítica (%)", ram_hot), False, False, 0)
        content.pack_start(Gtk.Separator(), False, False, 4)

        content.pack_start(section("Apariencia"), False, False, 0)
        content.pack_start(
            row("Usar colores del tema", theme_switch), False, False, 0
        )
        content.pack_start(
            row("Mostrar etiquetas GPU / RAM", labels_switch), False, False, 0
        )
        content.pack_start(Gtk.Separator(), False, False, 4)

        content.pack_start(section("Comportamiento"), False, False, 0)
        content.pack_start(
            row("Mostrar swap en el tooltip", swap_switch), False, False, 0
        )
        content.pack_start(
            row("Cerrar la ventana la oculta en la bandeja", close_switch),
            False,
            False,
            0,
        )
        content.pack_start(
            row("Arrancar al iniciar sesión", autostart_switch), False, False, 0
        )

        config_display = CONFIG_PATH
        home = os.path.expanduser("~")
        if config_display.startswith(home + os.sep):
            config_display = "~" + config_display[len(home):]
        note = Gtk.Label(
            label=(
                "Los cambios se aplican al instante.\n"
                f"Configuración: {config_display}"
            ),
            xalign=0,
        )
        note.set_line_wrap(True)
        note.set_max_width_chars(52)
        note.set_opacity(0.7)
        note.set_margin_top(10)
        content.pack_start(note, False, False, 0)

        widgets = {
            "interval": interval,
            "temp_warn": temp_warn,
            "temp_hot": temp_hot,
            "ram_warn": ram_warn,
            "ram_hot": ram_hot,
            "theme": theme_switch,
            "labels": labels_switch,
            "swap": swap_switch,
            "close": close_switch,
            "autostart": autostart_switch,
        }
        self._settings_widgets = widgets

        def changed(*_):
            if self._settings_updating:
                return
            self._settings_updating = True
            try:
                warn = int(temp_warn.get_value())
                hot = int(temp_hot.get_value())
                if hot <= warn:
                    hot = min(110, warn + 1)
                    temp_hot.set_value(hot)
                ram_low = int(ram_warn.get_value())
                ram_high = int(ram_hot.get_value())
                if ram_high <= ram_low:
                    ram_high = min(100, ram_low + 1)
                    ram_hot.set_value(ram_high)

                new_cfg = dict(self.config)
                new_cfg.update(
                    {
                        "refresh_seconds": round(float(interval.get_value()), 1),
                        "temp_warn": warn,
                        "temp_hot": hot,
                        "ram_warn": ram_low,
                        "ram_hot": ram_high,
                        "use_theme_colors": theme_switch.get_active(),
                        "show_labels": labels_switch.get_active(),
                        "show_swap": swap_switch.get_active(),
                        "hide_on_close": close_switch.get_active(),
                    }
                )
                self.config = _normalize_config(new_cfg)
                save_config(self.config)
                self._reschedule_timer()
                self._rerender()
            finally:
                self._settings_updating = False

        def autostart_changed(*_):
            if self._settings_updating:
                return
            want = autostart_switch.get_active()
            try:
                set_autostart(want)
            except OSError as exc:
                print(
                    f"No se pudo cambiar el arranque automático: {exc}",
                    file=sys.stderr,
                )
                self._settings_updating = True
                autostart_switch.set_active(not want)
                self._settings_updating = False

        for widget in (interval, temp_warn, temp_hot, ram_warn, ram_hot):
            widget.connect("value-changed", changed)
        for widget in (theme_switch, labels_switch, swap_switch, close_switch):
            widget.connect("notify::active", changed)
        autostart_switch.connect("notify::active", autostart_changed)

        def response(dlg, response_id):
            if response_id == Gtk.ResponseType.APPLY:
                self._reset_settings()
            else:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.connect("destroy", self._on_settings_destroyed)
        self.settings_dialog = dialog
        dialog.show_all()
        dialog.present()

    def _reset_settings(self):
        self.config = dict(DEFAULT_CONFIG)
        save_config(self.config)
        self._settings_updating = True
        try:
            widgets = self._settings_widgets or {}
            if "interval" in widgets:
                widgets["interval"].set_value(self.config["refresh_seconds"])
                widgets["temp_warn"].set_value(self.config["temp_warn"])
                widgets["temp_hot"].set_value(self.config["temp_hot"])
                widgets["ram_warn"].set_value(self.config["ram_warn"])
                widgets["ram_hot"].set_value(self.config["ram_hot"])
                widgets["theme"].set_active(self.config["use_theme_colors"])
                widgets["labels"].set_active(self.config["show_labels"])
                widgets["swap"].set_active(self.config["show_swap"])
                widgets["close"].set_active(self.config["hide_on_close"])
        finally:
            self._settings_updating = False
        self._reschedule_timer()
        self._rerender()

    # -- eventos -----------------------------------------------------------
    def _show(self):
        self.win.show_all()
        self.win.present()

    def _quit(self):
        self.GLib.idle_add(self.Gtk.main_quit)

    def _on_delete(self, *_):
        if self.indicator is not None and self.config.get("hide_on_close", True):
            self.win.hide()
            return True
        self._quit()
        return True

    # -- refresco ----------------------------------------------------------
    def _tick(self):
        self.ticks += 1
        if self.ticks % 20 == 0:
            self.reader.rediscover()
            self.palette = load_theme_palette()
        try:
            data = self.reader.sample()
        except Exception as exc:  # nunca tumbar la app por un sysfs raro
            self.footer.set_text(f"Error de lectura: {exc}")
            return True
        self.last_data = data
        if data["gpu_temp"] is not None:
            self.history.append(data["gpu_temp"])
            if len(self.history) > self.MAX_HISTORY:
                del self.history[: len(self.history) - self.MAX_HISTORY]
        self._render(data)
        return True

    def _render(self, data):
        temp = data["gpu_temp"]
        cfg = self.config
        palette = self._active_palette()
        self.active_palette = palette
        color, status_text = _color_for(
            temp, palette, cfg["temp_warn"], cfg["temp_hot"]
        )

        big = f"{temp:.0f}" if temp is not None else "—"
        self.big.set_markup(
            f'<span size="52000" foreground="{color}">{big}</span>'
            f'<span size="20000" foreground="{color}"> °C</span>'
        )
        self.status.set_markup(
            f'<span foreground="{color}">{status_text}</span>'
        )

        if data["approx"]:
            self.note.set_text(
                "Aproximación: paquete de la CPU (la UHD 630 no tiene sensor propio)"
            )
        else:
            self.note.set_text("Sensor térmico propio de la GPU")

        self.detail_values["source"].set_text(data["source"] or "—")
        self.detail_values["cpu_pkg"].set_text(_fmt(data["cpu_pkg"], " °C", 1))
        self.detail_values["pch"].set_text(_fmt(data["pch"], " °C", 1))

        if temp is None:
            bar_temp_color = palette["fg"]
        elif temp >= cfg["temp_hot"]:
            bar_temp_color = palette["error"]
        elif temp >= cfg["temp_warn"]:
            bar_temp_color = palette["warning"]
        else:
            bar_temp_color = palette["accent"]

        ram_pct = data.get("ram_percent")
        if ram_pct is None:
            bar_ram_color = palette["accent_light"]
        elif ram_pct >= cfg["ram_hot"]:
            bar_ram_color = palette["error"]
        elif ram_pct >= cfg["ram_warn"]:
            bar_ram_color = palette["warning"]
        else:
            bar_ram_color = palette["accent_light"]

        if ram_pct is None:
            self.detail_values["ram"].set_text("—")
            self.detail_values["ram"].set_tooltip_text("")
        else:
            ram_text = (
                f"{data['ram_used_gb']:.1f} / {data['ram_total_gb']:.1f} GB"
                f" · {ram_pct:.0f} %"
            )
            if ram_pct >= cfg["ram_hot"]:
                ram_color = palette["error"]
            elif ram_pct >= cfg["ram_warn"]:
                ram_color = palette["warning"]
            else:
                ram_color = palette["accent_light"]
            self.detail_values["ram"].set_markup(
                f'<span foreground="{ram_color}">{ram_text}</span>'
            )
            if cfg["show_swap"]:
                swap_total = data.get("swap_total_gb") or 0.0
                if swap_total > 0:
                    swap_tip = (
                        f"Swap: {data['swap_used_gb']:.1f} / {swap_total:.1f} GB"
                    )
                else:
                    swap_tip = "Swap: no configurada"
                self.detail_values["ram"].set_tooltip_text(swap_tip)
            else:
                self.detail_values["ram"].set_tooltip_text("")

        if data["freq"] is not None:
            freq_text = f"{data['freq']:.0f}"
            if data["freq_max"] is not None:
                freq_text += f" / {data['freq_max']:.0f} MHz"
            else:
                freq_text += " MHz"
        else:
            freq_text = "—"
        self.detail_values["freq"].set_text(freq_text)
        self.detail_values["activity"].set_text(_fmt(data["activity"], " %", 0))

        self.spark.queue_draw()

        stamp = time.strftime("%H:%M:%S")
        self.footer.set_text(
            f"Actualizado {stamp} · cada {cfg['refresh_seconds']:.1f} s"
        )

        if self.indicator is not None:
            temp_txt = f"{temp:.0f}°C" if temp is not None else "—"
            if ram_pct is not None:
                label = f"{temp_txt} · {ram_pct:.0f}%"
            else:
                label = temp_txt
            tip = f"{APP_NAME}: {label}"
            if data["approx"]:
                tip += " (aprox., paquete CPU)"
            try:
                self._tray_flip = not self._tray_flip
                name = "tray-a.png" if self._tray_flip else "tray-b.png"
                icon_file = os.path.join(self._tray_dir, name)
                make_tray_icon(
                    icon_file,
                    temp,
                    bar_temp_color,
                    ram_percent=ram_pct,
                    ram_color=bar_ram_color,
                    palette=palette,
                    show_labels=cfg["show_labels"],
                )
                self.indicator.set_icon_full(icon_file, tip)
            except Exception:
                pass
            try:
                self.indicator.set_label(label, label)
                self.indicator.set_title(tip)
            except Exception:
                pass

    # -- dibujo de la gráfica ---------------------------------------------
    def _draw_spark(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cr.set_source_rgba(0.10, 0.10, 0.13, 1.0)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        data = self.history
        if len(data) < 2 or width < 8:
            return

        low, high = min(data), max(data)
        span = max(high - low, 1.0)
        pad_x, pad_y = 2.0, 4.0
        usable_w = width - pad_x * 2
        usable_h = height - pad_y * 2

        def point(index, value):
            x = pad_x + usable_w * index / (len(data) - 1)
            y = pad_y + usable_h * (1.0 - (value - low) / span)
            return x, y

        cfg = self.config
        color, _ = _color_for(
            data[-1],
            getattr(self, "active_palette", None),
            cfg["temp_warn"],
            cfg["temp_hot"],
        )
        r, g, b = (
            int(color[1:3], 16) / 255.0,
            int(color[3:5], 16) / 255.0,
            int(color[5:7], 16) / 255.0,
        )

        # relleno bajo la curva
        cr.move_to(*point(0, data[0]))
        for i in range(1, len(data)):
            cr.line_to(*point(i, data[i]))
        cr.line_to(point(len(data) - 1, low)[0], height - pad_y)
        cr.line_to(point(0, low)[0], height - pad_y)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.18)
        cr.fill()

        # línea
        cr.move_to(*point(0, data[0]))
        for i in range(1, len(data)):
            cr.line_to(*point(i, data[i]))
        cr.set_source_rgba(r, g, b, 0.95)
        cr.set_line_width(1.6)
        cr.stroke()

        # último punto
        x, y = point(len(data) - 1, data[-1])
        cr.arc(x, y, 2.4, 0, 6.2832)
        cr.set_source_rgba(r, g, b, 1.0)
        cr.fill()


def run_gui(reader, use_tray, open_settings=False):
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception as exc:
        print(
            f"No se pudo cargar GTK3 ({exc}).\n"
            "Instala: sudo apt install python3-gi gir1.2-gtk-3.0",
            file=sys.stderr,
        )
        return 1

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print(
            "No hay entorno gráfico disponible. Usa: gpumonitor.py --cli",
            file=sys.stderr,
        )
        return 1

    MonitorApp(reader, use_tray=use_tray, open_settings=open_settings)
    Gtk.main()
    return 0


# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Monitor de temperatura de la iGPU Intel UHD Graphics 630"
    )
    parser.add_argument("--cli", action="store_true", help="salida de texto en la terminal")
    parser.add_argument("--once", action="store_true", help="con --cli, imprime una vez y sale")
    parser.add_argument("--json", action="store_true", help="imprime una muestra en JSON y sale")
    parser.add_argument("--interval", type=float, default=REFRESH_MS / 1000.0,
                        help="segundos entre lecturas en modo CLI (por defecto 1.5)")
    parser.add_argument("--no-tray", action="store_true", help="no usar la bandeja del sistema")
    parser.add_argument("--settings", action="store_true",
                        help="abrir la ventana con la configuración")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args(argv)

    reader = GpuReader()

    if args.json:
        return run_json(reader)
    if args.cli:
        return run_cli(reader, max(0.2, args.interval), args.once)
    return run_gui(
        reader, use_tray=not args.no_tray, open_settings=args.settings
    )


if __name__ == "__main__":
    sys.exit(main())
