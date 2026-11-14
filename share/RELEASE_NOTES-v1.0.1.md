# GPUMonitor 1.0.1

Versión de corrección: mejora visual del porcentaje de RAM en el icono del
panel.

## Cambios

- El símbolo `%` de la RAM ya no se solapa con la etiqueta `RAM`: ahora es más
  pequeño, está alineado con la base del número y tiene separación.
- Icono ligeramente más ancho para dar aire entre `34%` y `RAM`.
- Sin cambios en la lectura de sensores ni en el resto de funciones.

Para el detalle completo de la primera versión, consulta las notas de
[GPUMonitor 1.0.0](https://github.com/shary-hh/gpumonitor/releases/tag/v1.0.0).

## Instalación

### Paquete .deb

```bash
sudo apt install ./gpumonitor_1.0.1_all.deb
```

Si actualizas desde 1.0.0, el propio `apt` reemplaza la versión anterior:

```bash
sudo apt install ./gpumonitor_1.0.1_all.deb
```

### Desde el código

```bash
tar xzf gpumonitor-1.0.1.tar.gz
cd gpumonitor-1.0.1
./install.sh
```

## Capturas

![Ventana de GPUMonitor](https://raw.githubusercontent.com/shary-hh/gpumonitor/v1.0.1/docs/screenshot.png)

![Icono en el panel](https://raw.githubusercontent.com/shary-hh/gpumonitor/v1.0.1/docs/panel.png)

## Verificación

`SHA256SUMS` se adjunta a la release:

```bash
sha256sum -c SHA256SUMS
```

## Licencia

MIT © 2026 shary-hh.
