# Segunda prueba end-to-end — 2026-09-19

Preparación para repetir la instalación desde una SD limpia. Este documento no
certifica una prueba física realizada. KACE mantiene la versión 0.9.4-rc.2;
la identidad de esta iteración es el commit, no el número de versión.

- Rama de prueba: `test/e2e2-hardware-20260919`.
- Runtime corregido: `47a00c15739ac9c4d477f78dd9d71446d1c8d932`.
- Studio debe usar su contrato y bootstrap correspondientes a esta rama.
- Concurrencia: opción 1 aceptada. No guardar ediciones desde Mainsail/SSH
  durante la publicación de KACE; se conservan lock, comparación, snapshots y
  reemplazo atómico por archivo. No se garantiza CAS frente a otros escritores.

## Recorrido principal

1. Usar otra SD o respaldar la primera antes de regrabarla. El operador elige y
   confirma el dispositivo físico. Raspberry Pi 3, Mainsail pre-baked, SSH y
   verificación de lectura habilitados. Repetir GPIO 21 activo en bajo solo si
   el cableado sigue siendo el mismo. El bootstrap puede encender la impresora.
2. Esperar a que Studio complete escritura, verificación y provisión; expulsar
   desde Studio. Registrar el resultado de Windows y el de Studio por separado.
3. Insertar la SD en la Pi apagada, encenderla y usar Discovery. Registrar hora
   de encendido, detección y conexión; verificar actualización sin escaneo manual
   repetido. Anotar la IP actual, sin asumir la de la primera prueba.
4. Ejecutar el bootstrap desde Studio. Registrar estados de energía antes y
   después del dispositivo Moonraker. No pulsar el relé solo para probar la UI.
5. Elegir español, principiante y el mismo hardware: SKR 1.4/LPC1769, perfil
   Anet A8 2019, TMC2209 UART, dos Z con el segundo en E1, sin probe ni pantalla.
   Comprobar que las selecciones coinciden con el hardware conectado.
6. Compilar, descargar `firmware.bin`, copiarlo a la SD de la MCU y realizar
   manualmente el ciclo de apagado/inserción/encendido cuando KACE lo indique.
   Verificar la MCU y la identidad del firmware; no inferir flashing exitoso
   solo porque reaparece un dispositivo USB.
7. Omitir macros iniciales como en la primera pasada. Para desplegar desde KACE
   ejecutado **en esta misma Pi**, usar Moonraker local: `127.0.0.1:7125`.
   La publicación local verifica que el directorio corresponde al Klipper activo.
   Una IP LAN se trata como transporte remoto y no habilita esa publicación.
8. Aceptar la configuración revisada y, si hay cambios, RESTART. Debe finalizar
   sin copiar archivos manualmente, con Klipper Ready, identidad MCU verificada,
   configuración cargada y workflow COMPLETE. Abrir `printer.cfg` en Mainsail:
   el hardware de la instalación nueva debe estar allí, sin el listado largo
   de procedencia; la información de procedencia se conserva aparte.

## Evidencia y aceptación

Para cada etapa: acción del usuario → interfaz → evidencia Pi/MCU → resultado
→ fricción. Guardar logs y capturas sin contraseñas, claves ni Wi-Fi. Anotar los
commits instalados, hora, `cat /proc/sys/kernel/random/boot_id`, uptime, estados
de Klipper/Moonraker, rutas by-id/by-path, workflow y archivos antes/después.
Comparar boot_id antes y después de RESTART: un reinicio de la Pi es una anomalía
independiente cuyo origen debe investigarse.

Después del recorrido principal, y conservando evidencia, repetir la misma
propuesta para comprobar cero cambios y ausencia de reinicio innecesario.
La recuperación de una sesión interrumpida se prueba por separado, sin cortar
una escritura/compilación ni apagar la Pi: debe ofrecer continuar antes del
wizard, restaurar idioma/modo y ocultar acciones de firmware ya terminadas.

Éxito: instalación sin intervención manual en los archivos, configuración
realmente cargada y cierre visible en CLI/Studio. Tener Klipper Ready no valida
endstops, sentido de motores, probe ni heaters. El commissioning físico queda
para la siguiente etapa, bajo control del operador. Si un paso falla, preservar
el estado y documentarlo antes de cualquier corrección.
