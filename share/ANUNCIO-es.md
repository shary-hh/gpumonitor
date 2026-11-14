# GPUMonitor: temperatura de la iGPU Intel UHD 630 y RAM en el panel de Cinnamon

Hola a todos:

Quiero compartir **GPUMonitor**, una miniaplicación para **Linux Mint 22.3
Cinnamon** que muestra en el panel la temperatura de la iGPU **Intel UHD
Graphics 630** y el uso de **memoria RAM**, sin necesidad de abrir nada más.

- Repositorio: https://github.com/shary-hh/gpumonitor
- Descarga directa (.deb y tar.gz): https://github.com/shary-hh/gpumonitor/releases
- Licencia: MIT

## Aviso importante sobre la temperatura

La UHD 630 **no expone un sensor térmico propio en Linux** (no hay `hwmon` de
`i915`). Por eso el applet `gputemperature@silentage.com` muestra `NaN °C`: no
hay sensor que leer. GPUMonitor usa como **aproximación** la temperatura del
paquete de la CPU (misma oblea) y lo indica claramente con `≈` en el modo CLI y
con el texto «Aproximación» en la ventana. Si el kernel expone un sensor real,
la app lo detecta y lo usa automáticamente.

## Qué incluye

- Ventana GTK3 con temperatura grande, estado por colores y mini-gráfica.
- Icono en la bandeja con **`39° GPU | 34% RAM`** dibujado dentro del icono.
- Frecuencia real de la GPU y actividad mediante la residencia **RC6**.
- Temperaturas de contexto: paquete de CPU y chipset PCH.
- Uso de RAM y swap.
- **Colores adaptados al tema activo** de Cinnamon/GTK (acento, texto del panel,
  aviso y error).
- Modo CLI y salida JSON.
- Sin `sudo` para leer los sensores y sin demonios.

## Capturas

![Ventana de GPUMonitor](https://raw.githubusercontent.com/shary-hh/gpumonitor/main/docs/screenshot.png)

![Icono en el panel](https://raw.githubusercontent.com/shary-hh/gpumonitor/main/docs/panel.png)

## Instalación

### Paquete .deb (recomendado)

```bash
sudo apt install ./gpumonitor_1.0.1_all.deb
```

Dependencias: `python3-gi`, `gir1.2-gtk-3.0`, `python3-cairo` y
`gir1.2-ayatanaappindicator3-0.1` (apt las resuelve).

### Desde el código, solo para tu usuario

```bash
tar xzf gpumonitor-1.0.1.tar.gz
cd gpumonitor-1.0.1
./install.sh                # lanzador y comando gpumonitor
./install.sh --autostart    # además arranca al iniciar sesión
./install.sh --uninstall    # desinstalar
```

## Uso

```bash
gpumonitor                 # ventana + bandeja
gpumonitor --cli           # terminal en vivo
gpumonitor --cli --once    # una lectura
gpumonitor --json          # JSON para scripts
```

Si el icono del panel te parece pequeño, puedes subir la zona derecha de
Cinnamon:

```bash
gsettings set org.cinnamon panel-zone-icon-sizes \
  '[{"panelId": 1, "left": 0, "center": 0, "right": 32}]'
```

Para volver al tamaño original, usa `right: 24`.

## Probado en

- Linux Mint 22.3 Cinnamon (Zena)
- Kernel 7.0.0-43
- Intel UHD Graphics 630 (Coffee Lake GT2, `8086:3e92`, driver `i915`)
- Tema Mint-Y-Dark-Aqua

## Comentarios

Cualquier prueba en otras iGPU, kernels o temas es bienvenida. Si algo falla,
abre un issue en GitHub con la salida de:

```bash
gpumonitor --json
cat /etc/os-release | head -3
uname -r
```

¡Gracias!
