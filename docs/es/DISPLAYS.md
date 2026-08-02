# 🖥️ Guía de Compatibilidad de Pantallas

> **Filosofía de KACE:** detectar → clasificar → informar → recomendar.
> KACE nunca modifica ni deshabilita automáticamente la configuración de su pantalla.

---

## ¿Por qué es importante?

Klipper es un firmware **orientado a la web**. Sus interfaces principales son [Mainsail](https://docs.mainsail.xyz/) y [Fluidd](https://docs.fluidd.xyz/) — paneles de control basados en navegador que ofrecen control total de la impresora desde cualquier teléfono, tablet o PC.

Muchas impresoras OEM incluyen pantallas táctiles diseñadas **específicamente para el firmware Marlin**. Estas pantallas utilizan protocolos propietarios, puentes seriales específicos del fabricante o firmware de pantalla personalizado que asume el conjunto de comandos de Marlin. Cuando Klipper reemplaza a Marlin, estas pantallas suelen dejar de funcionar, no porque Klipper esté roto, sino porque la pantalla nunca fue diseñada para él.

> **Esto no es un error de KACE.** Es una limitación de compatibilidad de pantallas OEM.

---

## Definición de los Estados de Compatibilidad

| Estado | Significado |
|--------|-------------|
| 🟢 **COMPATIBLE** | Funciona de forma nativa en Klipper — sin problemas |
| 🟡 **PARCIAL** | Funciona con limitaciones; funcionalidad de menú reducida o ausente |
| 🔴 **NO COMPATIBLE** | Incompatible; puede causar pantalla negra, bucle de arranque o conflictos seriales |
| ⬜ **SIN PRUEBAS** | Sin datos de compatibilidad disponibles; resultado desconocido |

---

## Referencia de Tipos de Pantalla

### 🟢 Pantallas Compatibles

Compatibles de forma nativa con Klipper, sin configuración adicional:

| Tipo de Pantalla | Ejemplos | Notas |
|---|---|---|
| **LCD 12864 Estándar** | LCD original Ender 3, RepRapDiscount Smart LCD | Totalmente compatible |
| **mini12864** | BTT mini12864, pantalla del kit SKR 1.4 | Totalmente compatible |
| **ST7920** | Controlador RepRapDiscount Smart LCD | Totalmente compatible |
| **UC1701** | Variantes mini12864 | Totalmente compatible |
| **HD44780** | LCD de caracteres 20×4 | Totalmente compatible |
| **SSD1306 OLED** | Varios módulos OLED pequeños | Totalmente compatible |

---

### 🟡 Soporte Parcial

Estas pantallas pueden funcionar a un nivel básico pero probablemente tendrán menús faltantes, funcionalidad reducida o problemas menores:

| Tipo de Pantalla | Impresoras Comunes | Limitación Conocida |
|---|---|---|
| **TFT Serial (tft_serial)** | Artillery Sidewinder, Artillery Genius, Artillery Hornet, Ender 6, CR-10 Smart | Los menús seriales generalmente no funcionan bajo Klipper |
| **DWIN / DGUS (dwin_set)** | Varias | Requiere firmware de pantalla comunitario compatible — sensible a la versión |

**Enfoque recomendado para soporte parcial:** use la interfaz web (Mainsail/Fluidd) como interfaz principal. La pantalla puede mostrar el estado básico pero no es confiable para la navegación de menús.

---

### 🔴 Pantallas No Compatibles

Estas pantallas no son compatibles con Klipper sin modificaciones comunitarias significativas:

| Tipo / Sección | Impresoras Comunes | Problema |
|---|---|---|
| **t5uid1 (protocolo DGUS)** | Creality CR-6 SE | Firmware OEM propietario de Creality — Klipper no tiene soporte incorporado |
| **Neopixel / WS2812** | Varias | Fuera del alcance de configuración actual de KACE |
| **Dotstar / APA102** | Varias | Fuera del alcance de configuración actual de KACE |
| **Expansor GPIO SX1509** | Algunas placas MKS | No compatible con el motor de configuración de KACE |

---

## Compatibilidad de Impresoras OEM

### Creality CR-6 SE

**Estado:** 🔴 NO COMPATIBLE

La CR-6 SE utiliza una pantalla táctil DGUS propietaria de Creality con firmware OEM diseñado exclusivamente para Marlin. Klipper no tiene soporte incorporado para el protocolo `t5uid1` / DGUS.

**Síntomas comunes cuando la pantalla permanece conectada:**
- Pantalla negra al arrancar
- Bucle de arranque / Klipper no inicia
- Conflictos de comunicación serial

**Acción recomendada:** Desconecte físicamente el cable de la pantalla de la placa principal.

**Recurso comunitario:** La comunidad de código abierto ha desarrollado firmware de pantalla DGUS personalizado para la CR-6 SE. Busque: *"CR-6 SE Klipper DGUS firmware comunitario"*.

---

### Artillery Sidewinder X1 / X2

**Estado:** 🟡 PARCIAL

Utiliza una pantalla TFT serial diseñada para el protocolo TFT de Marlin. Bajo Klipper:
- La pantalla puede mostrar el estado básico de la impresora
- Los menús de navegación generalmente no funcionarán
- Algunos usuarios no reportan problemas; otros reportan conflictos seriales

**Acción recomendada:** Use Mainsail o Fluidd como interfaz principal. Mantenga la pantalla conectada si lo desea, pero no dependa de ella para el control.

---

### Artillery Genius

**Estado:** 🟡 PARCIAL

Misma situación TFT serial que el Sidewinder. Se recomienda la interfaz web para control completo.

---

### Artillery Hornet

**Estado:** 🟡 PARCIAL

Misma situación TFT serial. Se recomienda la interfaz web.

---

## Síntomas Comunes y Causas

| Síntoma | Causa Probable |
|---------|---------------|
| Pantalla negra después de que Klipper inicia | Firmware de pantalla incompatible (ej., t5uid1 en CR-6 SE) |
| La pantalla muestra "No Printer Attached" | El TFT serial no recibe respuestas con formato Marlin |
| Klipper no puede conectarse al MCU | La pantalla está ocupando o conflictuando con el puerto serial |
| El menú está congelado o no responde | El puente serial TFT no recibe las respuestas G-code esperadas de Marlin |
| Bucle de arranque / ciclo de reinicio de Klipper | El firmware de la pantalla está reiniciando el MCU vía línea DTR/reset |
| Menús parciales pero con entradas faltantes | El firmware TFT solo maneja parcialmente el formato de salida de Klipper |

---

## Enfoque Recomendado para Principiantes

1. **Desconecte la pantalla táctil OEM** (especialmente para CR-6 SE, impresoras Artillery)
2. **Instale Mainsail o Fluidd** en su Raspberry Pi
3. **Acceda a su impresora desde cualquier dispositivo** en su red local
4. Disfrute de una interfaz mejor que la pantalla OEM

Mainsail y Fluidd ofrecen:
- Estado en tiempo real de la impresora y gráficos de temperatura
- Gestión y carga de archivos Gcode
- Historial y estadísticas de impresión
- Integración de cámara web
- Edición completa de macros y configuración
- UI responsiva compatible con móviles

---

## Para Usuarios Avanzados

Si desea experimentar con la compatibilidad de pantallas OEM:

- **Pantallas DGUS/DWIN:** Busque firmware de pantalla Klipper comunitario para su modelo específico. La versión del firmware debe coincidir exactamente con su hardware de pantalla.
- **Pantallas TFT serial:** Algunos miembros de la comunidad han tenido éxito parcial configurando `[respond]` de Klipper y usando reenvío personalizado de G-code. Esto es experimental.
- **Neopixel/RGB:** Klipper soporta neopixel de forma nativa mediante la sección `[neopixel]` — KACE simplemente no lo configura automáticamente. Puede agregarlo manualmente después de la generación.

KACE nunca eliminará ni deshabilitará sus secciones de configuración de pantalla. Usted es libre de experimentar.

---

## Ver También

- [Configuración de Pantalla de Klipper](https://www.klipper3d.org/Config_Reference.html#display) — referencia oficial
- [Documentación de Mainsail](https://docs.mainsail.xyz/)
- [Documentación de Fluidd](https://docs.fluidd.xyz/)
- [Guía de pruebas de KACE](TESTING.md)
- [Resumen de la arquitectura de KACE](../../README.md#architecture)
