# GPUMonitor 1.0.0

Primera versión pública de **GPUMonitor**, una miniaplicación para Linux Mint
22.3 Cinnamon que muestra la temperatura de la iGPU **Intel UHD Graphics 630**
y el uso de **memoria RAM** directamente en el panel.

## Destacado

- Ventana GTK3, icono de bandeja y modo CLI/JSON.
- Icono con `39° GPU | 34% RAM` dibujado dentro del propio icono.
- Frecuencia real de la GPU y actividad mediante la residencia RC6.
- Temperaturas de contexto: paquete de CPU y chipset PCH.
- RAM y swap desde `/proc/meminfo`.
- Colores adaptados al tema activo de Cinnamon/GTK.
- Sin `sudo` para leer sensores y sin demonios.

## Aviso sobre la temperatura

La UHD 630 **no expone un sensor térmico propio en Linux** (no hay `hwmon` de
`i915`). Por eso el applet `gputemperature@silentage.com` muestra `NaN °C`.
GPUMonitor usa como aproximación la temperatura del paquete de la CPU (misma
oblea) y lo indica claramente con `≈` en CLI y «Aproximación» en la ventana. Si
el kernel expone un sensor real, la app lo usa automáticamente.

## Instalación

### Paquete .deb (recomendado)

```bash
sudo apt install ./gpumonitor_1.0.0_all.deb
```

### Desde el código

```bash
tar xzf gpumonitor-1.0.0.tar.gz
cd gpumonitor-1.0.0
./install.sh
./install.sh --autostart   # opcional
```

## Capturas

![Ventana de GPUMonitor](https://raw.githubusercontent.com/shary-hh/gpumonitor/v1.0.0/docs/screenshot.png)

![Icono en el panel](https://raw.githubusercontent.com/shary-hh/gpumonitor/v1.0.0/docs/panel.png)

## Probado en

- Linux Mint 22.3 Cinnamon (Zena)
- Kernel 7.0.0-43
- Intel UHD Graphics 630 (Coffee Lake GT2, `8086:3e92`, driver `i915`)
- Tema Mint-Y-Dark-Aqua

## Verificación

`SHA256SUMS` se adjunta a la release. Para comprobar las descargas:

```bash
sha256sum -c SHA256SUMS
```

## Licencia

MIT © 2026 shary-hh.
