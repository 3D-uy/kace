# Testes e validação

O guia técnico canônico é [Testing guide (English)](../en/TESTING.md). Nele são mantidas as camadas de testes, o commit fixado do Klipper, as classificações da matriz e o mapeamento exato para o CI.

## Comandos principais

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
python tests/matrix/run_matrix.py --profile full
python tests/run_tests.py --full-klipper-sweep --verbose
```

As matrizes rápida e completa usam Docker e o parser real de uma revisão fixada do Klipper. Uma rejeição segura esperada não é contada como PASS. Nenhum teste deve gravar em hardware físico.

Use --update-snapshots somente quando uma alteração intencional modificar a saída gerada e revise cada diferença antes de confirmá-la.
