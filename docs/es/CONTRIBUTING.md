# Contribuir a KACE

La guía canónica y actualizada es [Contributing to KACE (English)](../en/CONTRIBUTING.md). Allí se mantienen los contratos del repositorio, la gestión de dependencias, los requisitos para boards y snapshots, y la lista de comprobación de pull requests.

## Validación mínima

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

Mantén cada cambio pequeño y con un único propósito. No actualices snapshots para ocultar un fallo, no accedas a hardware físico desde tests y valida cualquier cambio de `scripts/bootstrap.sh` también contra KACE Studio.

Los problemas de seguridad deben comunicarse según [SECURITY.md](../../SECURITY.md).
