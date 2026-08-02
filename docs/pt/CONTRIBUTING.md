# Contribuindo com o KACE

O guia canônico e atualizado é [Contributing to KACE (English)](../en/CONTRIBUTING.md). Nele são mantidos os contratos do repositório, a gestão de dependências, os requisitos para boards e snapshots e a lista de verificação de pull requests.

## Validação mínima

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

Mantenha cada alteração pequena e com um único objetivo. Não atualize snapshots para esconder uma falha, não acesse hardware físico nos testes e valide qualquer alteração em `scripts/bootstrap.sh` também no KACE Studio.

Problemas de segurança devem ser comunicados conforme [SECURITY.md](../../SECURITY.md).
