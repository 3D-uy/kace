# KACE — Roadmap

🌐 [English](../../ROADMAP.md) · [Español](../../docs/es/ROADMAP.md) · [Português](../../docs/pt/ROADMAP.md)

Prioridades deste código, sem datas prometidas ou afirmações de qualificação concluída. Os guias de release continuam sendo a autoridade dos gates; este roadmap não altera versões, hashes, targets de firmware nem pins.

## 📍 Disponível no código

Existem configuração guiada, publicação revisada, recuperação persistente, verificação da identidade de firmware e validação automática em camadas. Seus limites estão em [Escopo (EN)](../../docs/en/SUPPORT_SCOPE.md). O comportamento do código deve ser distinguido do candidato distribuído imutável.

## 🧭 Prioridades

| Prioridade | Resultado exigido | Referência |
| --- | --- | --- |
| 1 · Validação do código | Conciliar a suíte completa, cargas com Klipper fixado e gate de cenários revisados com a árvore final; preservar falhas e skips com suas causas. | [Testes](../DEVELOPMENT.md) |
| 2 · Qualificação controlada | Registrar placa/MCU exata, armazenamento, entrega de firmware, ativação, recuperação e preparação física. A aceitação do parser não basta. | [Hardware (EN)](../../docs/HARDWARE_TESTING.md) |
| 3 · Alinhamento de release | Em uma release autorizada separadamente, alinhar identidades de runtime com commit, instalador e bootstrap; validar depois o par Studio. Não publicar sem a evidência exigida. | [Release (EN)](../../docs/RELEASE.md) |
| 4 · Manutenção | Manter as entradas EN/ES/PT alinhadas; acrescentar regressões específicas para defeitos demonstrados e suporte revisado, preservando contratos de segurança. | [Contribuição](../DEVELOPMENT.md) |

## Limites de escopo

Novas plataformas host, migração arbitrária de perfis upstream, múltiplas extrusoras e gestão após a instalação exigem projeto e evidência separados. Não são prometidos por aparecerem no catálogo. A geometria já separa áreas imprimíveis e alcançáveis; isso não implica suporte IDEX/toolchanger.

[Voltar ao README](README.md)
