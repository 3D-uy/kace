# 🖥️ Configuración y soporte de pantallas

Revisado el 27 de septiembre de 2026 contra las dos revisiones oficiales de Klipper citadas abajo.

## Qué soporta KACE actualmente

El soporte del controlador en Klipper, una configuración válida y la compatibilidad
eléctrica son tres requisitos distintos. El nombre de un driver o un conector EXP
no establece el módulo exacto, pinout, alimentación, niveles de señal ni cableado.

**Ninguna pareja física de placa/pantalla del catálogo actual de KACE tiene evidencia
suficiente del módulo y cableado para generar una configuración activa guiada.**
Un resultado desconocido bloquea la generación incluso con selección manual o
riesgo aceptado. Las clasificaciones inseguras mantienen sus restricciones.
Las etiquetas heredadas `supported`, `partial` o de adaptadores en los datos no
certifican hardware.

KACE comprueba la configuración efectiva, includes y artefactos que genera,
conserva o publica durante la instalación inicial y sus reanudaciones pendientes.
Después de `DONE` (`COMPLETE` en el checkpoint de firmware), los cambios del usuario
quedan fuera de su responsabilidad: no hay monitorización, revalidación ni gestión
de esas modificaciones. Iniciar expresamente otra instalación es un flujo separado.

## Qué ocurre con la configuración

| Ruta | Comportamiento actual |
|---|---|
| Sin pantalla (`none`) | Omite los bloques de pantalla del nuevo hardware generado. No ordena borrar archivos manuales ajenos del destino. |
| Detección automática o pantalla física seleccionada con evidencia desconocida | Rechaza la generación; tener pines aparentemente completos o aceptar el riesgo no aporta evidencia de hardware. |
| Ruta restrictiva `unsafe` | La selección explícita exige reconocer el riesgo. El renderizador puede producir una referencia comentada inactiva, nunca una configuración activa certificada eléctricamente. Una referencia insegura automática también puede comentarse. |
| Hardware generado guardado, macros o sus includes | Se vuelven a comprobar antes de publicar y reanudar el flujo pendiente, incluso si no hay cambios. Las etiquetas guardadas no permiten eludir el control. |
| `[display]` o include exclusivamente manual ya existente en el destino | Puede conservarse tras comprobar configuración efectiva y requisitos del driver/transporte, con advertencia de verificación eléctrica. No certifica todas las opciones ni las conexiones físicas. |

Un include alcanzado desde hardware/macros generados conserva esas restricciones
aunque también lo referencie un archivo manual. La conservación es condicional;
KACE no promete mantener activa toda sección de pantalla del origen.

## Las 14 entradas físicas del catálogo

Son claves de selección de KACE, **no catorce nombres de sección nativos de Klipper**.
Todas quedan sujetas a las restricciones de evidencia anteriores.

| Clave KACE | Sintaxis oficial o límite |
|---|---|
| `display` | `[display]` con `lcd_type` soportado y sus opciones obligatorias |
| `st7920` | `lcd_type: st7920` dentro de `[display]` |
| `emulated_st7920` | `lcd_type: emulated_st7920` dentro de `[display]` |
| `hd44780` | `lcd_type: hd44780` dentro de `[display]` |
| `hd44780_spi` | `lcd_type: hd44780_spi` dentro de `[display]` |
| `aip31068_spi` | `lcd_type: aip31068_spi` dentro de `[display]` |
| `uc1701` | `lcd_type: uc1701` dentro de `[display]` |
| `ssd1306` | `lcd_type: ssd1306` dentro de `[display]` |
| `sh1106` | `lcd_type: sh1106` dentro de `[display]` |
| `btt_tft35` | Etiqueta de familia, no sección ni driver nativo. Un nombre de modo/revisión no certifica cableado. |
| `mks_mini12864` | Etiqueta de familia, no sección ni driver nativo. Sin inferencia universal de SPI/FSMC. |
| `dwin_set` | Etiqueta OEM heredada, sin sección ni driver nativo en las revisiones examinadas. |
| `tft_serial` | Etiqueta OEM heredada, sin sección ni driver nativo en las revisiones examinadas. |
| `t5uid1` | Sin sección/driver nativo en las revisiones examinadas; KACE conserva su política restrictiva. |

En un `[display]` mantenido manualmente, `lcd_type` es obligatorio. Algunos campos
adicionales obligatorios son `cs_pin`, `sclk_pin`, `sid_pin` para ST7920;
`rs_pin`, `e_pin`, `d4_pin` a `d7_pin` para HD44780; `latch_pin` para
HD44780_SPI/AIP31068_SPI; y `cs_pin`, `a0_pin` para UC1701. Emulated ST7920
requiere `en_pin` y las tres opciones de pines SPI por software. SSD1306/SH1106
pueden usar I2C o SPI; elegir SPI exige `cs_pin` y `dc_pin`. Los buses por software
necesitan todos sus pines. Los defaults de bus y los pines MCU válidos dependen del
hardware seleccionado. Estas listas **no son configuraciones listas para activar**.
Consultá la referencia oficial para los requisitos completos y opciones adicionales.

## Identidad OEM y módulos auxiliares

Los nombres oficiales exactos `printer-creality-ender3-2018.cfg` y
`printer-creality-ender3pro-2020.cfg` identifican el consejo genérico Ender 3;
`printer-creality-ender3-v2-2020.cfg` identifica V2 por separado. Los alias históricos
explícitos están en `data/displays.yaml`. Neo, S1, Max, archivos renombrados y futuras
variantes no heredan pantalla por coincidencia parcial. Reconocer un perfil no
identifica ni certifica la pantalla conectada, ni instala firmware comunitario.

Las secciones de software de Klipper como `[display_status]`, `[display_data ...]`,
`[display_template ...]` y `[menu ...]` son distintas de las pantallas físicas.
La etiqueta heredada `lcd_menu` de KACE no es una sección nativa para copiar al
archivo. Estas funciones de software tienen sus propios requisitos.

Los módulos nativos `[neopixel ...]`, `[dotstar ...]`, `[adxl345 ...]` y
`[sx1509 ...]` no dejan de estar soportados por Klipper porque el manejador avanzado
genérico de KACE los emita como comentarios. Ese manejador conserva referencias,
no instalaciones completas validadas. Los contratos existentes de dependencias
de hardware por placa son independientes. **`[pca9685]` no es una sección autónoma
válida: no la descomentes.** PCA9685 es interno de Replicape; KACE no lo convierte
a `[replicape]`.

## Diagnosticar un problema de pantalla

Leé el error real de Klipper e identificá placa, revisión de pantalla, conexión y
configuración efectiva. Una pantalla negra por sí sola no demuestra conflicto
de protocolo, memoria dañada, reset del MCU ni apagado de Linux. No uses consejos
genéricos de familia OEM como receta de cableado o flasheo. Mainsail/Fluidd son
interfaces web separadas, normalmente conectadas mediante Moonraker; usarlas no
demuestra que una pantalla conectada sea eléctricamente segura. La provisión de
Studio y la conectividad SSH también son independientes del soporte del driver LCD.

## Referencias oficiales y límites

- [Referencia de configuración fijada por KACE](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/docs/Config_Reference.md#display-support).
- [Registro de drivers LCD de la revisión fijada](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/klippy/extras/display/display.py).
- [Referencia de la revisión posterior archivada](https://github.com/Klipper3d/klipper/blob/ce7002bedf37e938bb483572949f3703ac6476cb/docs/Config_Reference.md#display-support).
- [Sitio oficial de referencia](https://www.klipper3d.org/Config_Reference.html#display-support), que puede cambiar después de esas revisiones.
- [Alcance de KACE](../en/SUPPORT_SCOPE.md) y [guía de pruebas](../DEVELOPMENT.md), en inglés.

La revisión posterior archivada no se presenta como el HEAD actual de upstream.
Estas comprobaciones no certifican una pantalla física ni constituyen una prueba E2E de hardware.
