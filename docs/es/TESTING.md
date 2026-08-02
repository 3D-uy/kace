# Pruebas y validación

La guía técnica canónica es [Testing guide (English)](../en/TESTING.md). Allí se mantienen las capas de pruebas, el commit fijado de Klipper, las clasificaciones de la matriz y la correspondencia exacta con CI.

## Comandos principales

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
python tests/matrix/run_matrix.py --profile full
python tests/run_tests.py --full-klipper-sweep --verbose
```

La matriz rápida y la completa usan Docker y el parser real de una revisión fijada de Klipper. Un rechazo seguro esperado no se cuenta como PASS. Ningún test debe escribir en hardware físico.

Usa --update-snapshots únicamente cuando un cambio intencional modifica la salida generada, y revisa cada diferencia antes de confirmarla.
