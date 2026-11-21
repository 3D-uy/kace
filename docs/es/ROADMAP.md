# KACE — Roadmap

🌐 [English](../../ROADMAP.md) · [Español](../../docs/es/ROADMAP.md) · [Português](../../docs/pt/ROADMAP.md)

Prioridades de este código, sin fechas prometidas ni afirmaciones de calificación completada. Las guías de release siguen siendo la autoridad para los gates; este roadmap no modifica versiones, hashes, targets de firmware ni pins.

## 📍 Disponible en código

Existen configuración guiada, publicación revisada, recuperación persistente, verificación de identidad del firmware y validación automática por capas. Sus límites están en [Alcance (EN)](../../docs/en/SUPPORT_SCOPE.md). El comportamiento del código debe distinguirse del candidato distribuido inmutable.

El mapeo revisado de conectores TMC extraíbles cubre diez perfiles exactos; los ajustes eléctricos entre modelos siguen requiriendo revisión del usuario. Ver [alcance (EN)](../TMC_SOCKET_MAPPING.md).

La geometría Z de la sonda se revisa antes de preparar firmware; los flujos
inconclusos con firmware verificado pueden revisar su mínimo Z guardado o un
offset conocido de sonda personalizada sin descartar esa evidencia. La calificación aún debe comprobar rechazo temprano,
cancelación, corrección guardada y activación/verificación completas sobre el
candidato exacto; estas comprobaciones no calibran la sonda ni completan solas
una instalación.

## Estado de correcciones en código — 2026-11-15

Este árbol ya implementa instalación fresca, recibos durables, publicación recuperable del runtime, confirmación explícita del área imprimible y force_move desactivado por defecto. Software describe la configuración nueva; la indicación de sonda ya pasa comprobaciones locales de presentación. Los puntos siguientes conservan el orden de calificación y la justificación histórica, no significan que estos cambios aún falten en código. Las dimensiones físicas de cama son desconocidas; las coordenadas utilizables requieren evidencia externa y confirmación del usuario.

Las regresiones locales no califican el runtime instalado ni el EXE distribuido. Quedan alineación inmutable de fuentes/paquete, GitHub Actions en runner limpio, mediciones Pi 3B, flecha arriba real, diagnóstico MCU/reinicio y E2E manuales. Los lanzadores antiguos y las sesiones Python directas no participan del nuevo lock del actualizador: detener esas sesiones antes de una actualización controlada. Estas pruebas de código no autorizan una actualización real.

## 🧭 Prioridades

Mejora de UX pendiente: reorganizar el volumen, el área imprimible, el recorrido
de la boquilla y la referencia de homing de la revisión del perfil en un resumen
compacto con detalles opcionales. Aclarar las dimensiones nominales e imprimibles
y las posiciones configuradas y medidas; conservar cálculos, traducciones y navegación.

Investigación pendiente: la flecha arriba muestra una secuencia literal en la
sesión de KACE actualmente en uso. Identificar el runtime y la ruta de terminal
activos y verificar el historial en esa sesión; el soporte de readline en el
código fuente no demuestra que la sesión distribuida lo esté usando.

Presentación de revisión de sonda pendiente: mantener destacado el valor Z
provisional y mostrar la indicación de calibración en blanco y en una línea si
el ancho lo permite, con ajuste legible en terminales angostas. Conservar EN/ES/PT.

Revisión de UX pendiente en Software: aclarar que la selección Mainsail/Fluidd
se refiere a la nueva configuración, no a instalar interfaces web. Simplificar
la ayuda y retirar las opciones que prometen conservar includes de la instalación
anterior. Las dependencias que el nuevo archivo seleccione sí deben validarse.

Política de instalación implementada: KACE realiza instalaciones
nuevas. Si existen printer.cfg o macros.cfg, informar al usuario y reemplazarlos
por los nuevos; no fusionar SAVE_CONFIG, calibraciones, macros ni includes antiguos.
Esto sustituye la propuesta anterior de conservar el PID al resolver el conflicto
observado entre watermark del perfil y PID guardado en la Pi (READY_TO_DEPLOY).
Preparar y validar primero el árbol nuevo, respaldar los archivos anteriores
fuera de los includes activos y publicar mediante la transacción existente con
recuperación ante fallos. Si no se generan macros, retirar el macros.cfg anterior
y sus referencias activas. No borrar indiscriminadamente el directorio de configuración.
Investigar por separado el apagado de Klipper por pérdida de comunicación con la
MCU; su causa no está verificada.

Orden del plan acordado para corregir de a uno:
1. Implementar instalación limpia y recuperación, incluyendo reanudación y el
   flujo separado de configuración; probar reemplazo con archivos antiguos,
   SAVE_CONFIG, includes rotos, macros omitidas e interrupciones. Mantener las
   validaciones de la configuración nueva y la aprobación de aplicación existente.
2. Diagnosticar comunicación MCU antes de la validación final en hardware.
3. Verificar y corregir historial de flecha arriba en la sesión real de Studio/Pi.
4. Completar la revisión de «calibrar después»: ya hay cambios locales que evitan
   la segunda confirmación del mínimo compatible, pendientes de revisión integral
   de pruebas, entrega y comprobación en Pi; no representan calibración física.
5. Ajustar en blanco la indicación PROBE_CALIBRATE de la revisión de sonda.
6. Simplificar la pantalla Mainsail/Fluidd conforme a instalación limpia.
7. Reorganizar volumen, geometría y termistores con resumen y detalles opcionales.
8. Unificar mensajes EN/ES/PT, validar Studio fuente/empaquetado y KACE instalado,
   y comprobar un recorrido completo sin atribuir éxito a una simple reconexión.

Este plan no autoriza una ejecución inmediata: se implementará un punto por vez
cuando el usuario lo indique. El diagnóstico actual no modificó archivos de la Pi.

El código incluye recomendaciones de placas en una lista común, números de selección amarillos, navegación Volver entre pasos interactivos y reutilización del homing revisado. El cuestionario continuo conserva explicaciones en recuadros, el dibujo de la sonda y la revisión completa del perfil; los catálogos muestran una vista acotada y filtros opcionales sobre todas las entradas, sin páginas. El resumen generado mantiene pendientes la aplicación y la verificación. Crowsnest distingue archivos y estado del servicio. Validar estos recorridos, incluida la cancelación y corrección del rango de la sonda, en la Pi real y el candidato distribuido exacto; las regresiones de código no acreditan la calificación física.

| Prioridad | Resultado requerido | Referencia |
| --- | --- | --- |
| 1 · Validación del código | Conciliar la suite completa, cargas con Klipper fijado y gate de escenarios revisados contra el árbol final; conservar fallos y skips con sus causas. | [Pruebas](../DEVELOPMENT.md) |
| 2 · Calificación controlada | Registrar placa/MCU exacta, almacenamiento, entrega de firmware, activación, recuperación y puesta en marcha física. La aceptación del parser no basta. | [Hardware (EN)](../../docs/HARDWARE_TESTING.md) |
| 3 · Alineación de release | En una release autorizada por separado, alinear identidades del runtime con commit, instalador y bootstrap; validar después el par Studio. No publicar sin evidencia requerida. | [Release (EN)](../../docs/RELEASE.md) |
| 4 · Mantenimiento | Mantener las entradas EN/ES/PT alineadas; añadir regresiones específicas para defectos demostrados y soporte revisado, preservando contratos de seguridad. | [Contribución](../DEVELOPMENT.md) |

## Límites de alcance

Nuevas plataformas host, migración arbitraria de perfiles upstream, múltiples extrusores y gestión posterior a la instalación requieren diseño y evidencia separados. No se prometen por aparecer en el catálogo. La geometría ya separa áreas imprimibles y alcanzables; eso no implica soporte IDEX/toolchanger.

[Volver al README](README.md)
