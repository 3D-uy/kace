# KACE — Roadmap

🌐 [English](../../ROADMAP.md) · [Español](../../docs/es/ROADMAP.md) · [Português](../../docs/pt/ROADMAP.md)

Prioridades de este código, sin fechas prometidas ni afirmaciones de calificación completada. Las guías de release siguen siendo la autoridad para los gates; este roadmap no modifica versiones, hashes, targets de firmware ni pins.

## 📍 Disponible en código

Existen configuración guiada, publicación revisada, recuperación persistente, verificación de identidad del firmware y validación automática por capas. Sus límites están en [Alcance (EN)](../../docs/en/SUPPORT_SCOPE.md). El comportamiento del código debe distinguirse del candidato distribuido inmutable.

El mapeo revisado de conectores TMC extraíbles cubre diez perfiles exactos; los ajustes eléctricos entre modelos siguen requiriendo revisión del usuario. Ver [alcance (EN)](../TMC_SOCKET_MAPPING.md).

## 🧭 Prioridades

| Prioridad | Resultado requerido | Referencia |
| --- | --- | --- |
| 1 · Validación del código | Conciliar la suite completa, cargas con Klipper fijado y gate de escenarios revisados contra el árbol final; conservar fallos y skips con sus causas. | [Pruebas](../DEVELOPMENT.md) |
| 2 · Calificación controlada | Registrar placa/MCU exacta, almacenamiento, entrega de firmware, activación, recuperación y puesta en marcha física. La aceptación del parser no basta. | [Hardware (EN)](../../docs/HARDWARE_TESTING.md) |
| 3 · Alineación de release | En una release autorizada por separado, alinear identidades del runtime con commit, instalador y bootstrap; validar después el par Studio. No publicar sin evidencia requerida. | [Release (EN)](../../docs/RELEASE.md) |
| 4 · Mantenimiento | Mantener las entradas EN/ES/PT alineadas; añadir regresiones específicas para defectos demostrados y soporte revisado, preservando contratos de seguridad. | [Contribución](../DEVELOPMENT.md) |

## Límites de alcance

Nuevas plataformas host, migración arbitraria de perfiles upstream, múltiples extrusores y gestión posterior a la instalación requieren diseño y evidencia separados. No se prometen por aparecer en el catálogo. La geometría ya separa áreas imprimibles y alcanzables; eso no implica soporte IDEX/toolchanger.

[Volver al README](README.md)
