# KACE — Roadmap

🌐 [English](../../ROADMAP.md) · [Español](../../docs/es/ROADMAP.md) · [Português](../../docs/pt/ROADMAP.md)

Prioridades deste código, sem datas prometidas ou afirmações de qualificação concluída. Os guias de release continuam sendo a autoridade dos gates; este roadmap não altera versões, hashes, targets de firmware nem pins.

## 📍 Disponível no código

Existem configuração guiada, publicação revisada, recuperação persistente, verificação da identidade de firmware e validação automática em camadas. Seus limites estão em [Escopo (EN)](../../docs/en/SUPPORT_SCOPE.md). O comportamento do código deve ser distinguido do candidato distribuído imutável.

O mapeamento revisado de conectores TMC removíveis cobre dez perfis exatos; os ajustes elétricos entre modelos ainda exigem revisão do usuário. Veja [escopo (EN)](../TMC_SOCKET_MAPPING.md).

A geometria Z da sonda é revisada antes de preparar firmware; fluxos incompletos
com firmware verificado podem revisar o mínimo Z salvo ou um offset conhecido
de sonda personalizada sem descartar essa evidência. A qualificação ainda deve verificar rejeição antecipada, cancelamento,
correção salva e ativação/verificação completas no candidato exato; essas
verificações não calibram a sonda nem concluem sozinhas uma instalação.

## 🧭 Prioridades

Melhoria de UX pendente: reorganizar volume, área imprimível, curso do bico e
referência de homing na revisão do perfil em um resumo compacto com detalhes
opcionais. Esclarecer dimensões nominais e imprimíveis e posições configuradas
e medidas; preservar cálculos, traduções e navegação.

Investigação pendente: a seta para cima mostra uma sequência literal na sessão
atual do KACE. Identificar o runtime e o caminho do terminal ativos e verificar
o histórico nessa sessão; o suporte a readline no código-fonte não comprova que
a sessão distribuída o esteja usando.

Apresentação da revisão da sonda pendente: manter o valor Z provisório destacado
e mostrar a indicação de calibração em branco e em uma linha quando couber, com
quebra legível em terminais estreitos. Preservar EN/ES/PT.

Revisão de UX pendente em Software: esclarecer que Mainsail/Fluidd seleciona a
nova configuração, não instala interfaces web. Simplificar a ajuda e retirar
opções que prometem preservar includes antigos. Validar as dependências escolhidas
pela nova configuração.

Decisão de produto pendente: KACE realiza instalações novas. Informar quando
printer.cfg ou macros.cfg existir e substituí-los pelos novos arquivos, sem mesclar
SAVE_CONFIG, calibrações, macros ou includes antigos. Isso substitui a proposta
de preservar PID no conflito watermark/PID observado no Pi (READY_TO_DEPLOY).
Preparar e validar a nova árvore primeiro, salvar os arquivos antigos fora dos
includes ativos e publicar pela transação recuperável existente. Se macros forem
omitidas, retirar o macros.cfg antigo e suas referências ativas. Não apagar
indiscriminadamente o diretório de configuração. Investigar separadamente a perda
de comunicação MCU do Klipper; a causa continua não verificada.

Ordem de implementação, um item por vez:
1. Instalação limpa e recuperação, incluindo retomada e fluxo separado de configuração;
   testar arquivos antigos, SAVE_CONFIG, includes quebrados, macros omitidas e
   interrupções. Manter validação da nova árvore e aprovação de publicação existente.
2. Diagnosticar comunicação MCU antes da validação final em hardware.
3. Verificar/corrigir histórico da seta para cima na sessão real Studio/Pi.
4. Concluir revisão de calibração adiada: alterações locais já retiram a segunda
   confirmação do mínimo compatível; faltam revisão integral das regressões,
   entrega e verificação no Pi. Isso não representa calibração física.
5. Mostrar em branco a indicação PROBE_CALIBRATE da revisão da sonda.
6. Simplificar Mainsail/Fluidd conforme a instalação limpa.
7. Reorganizar volume, geometria e termistores em resumo e detalhes opcionais.
8. Alinhar mensagens EN/ES/PT, verificar Studio fonte/empacotado e KACE instalado
   e testar o fluxo completo sem inferir conclusão pela reconexão.

O plano não implica execução imediata: implementar cada item quando o usuário
solicitar. O diagnóstico atual não alterou arquivos de configuração do Pi.

O código inclui recomendações de placas na mesma lista, números de seleção amarelos, navegação Voltar entre etapas interativas e reutilização do homing revisado. O questionário contínuo preserva explicações em quadros, o desenho da sonda e a revisão completa do perfil; os catálogos mostram uma prévia limitada e filtros opcionais em todas as entradas, sem páginas. O resumo gerado mantém a aplicação e a verificação pendentes. O Crowsnest distingue arquivos e estado do serviço. Validar esses fluxos, incluindo o cancelamento e a correção dos limites da sonda, no Pi real e no candidato distribuído exato; regressões de código não comprovam qualificação física.

| Prioridade | Resultado exigido | Referência |
| --- | --- | --- |
| 1 · Validação do código | Conciliar a suíte completa, cargas com Klipper fixado e gate de cenários revisados com a árvore final; preservar falhas e skips com suas causas. | [Testes](../DEVELOPMENT.md) |
| 2 · Qualificação controlada | Registrar placa/MCU exata, armazenamento, entrega de firmware, ativação, recuperação e preparação física. A aceitação do parser não basta. | [Hardware (EN)](../../docs/HARDWARE_TESTING.md) |
| 3 · Alinhamento de release | Em uma release autorizada separadamente, alinhar identidades de runtime com commit, instalador e bootstrap; validar depois o par Studio. Não publicar sem a evidência exigida. | [Release (EN)](../../docs/RELEASE.md) |
| 4 · Manutenção | Manter as entradas EN/ES/PT alinhadas; acrescentar regressões específicas para defeitos demonstrados e suporte revisado, preservando contratos de segurança. | [Contribuição](../DEVELOPMENT.md) |

## Limites de escopo

Novas plataformas host, migração arbitrária de perfis upstream, múltiplas extrusoras e gestão após a instalação exigem projeto e evidência separados. Não são prometidos por aparecerem no catálogo. A geometria já separa áreas imprimíveis e alcançáveis; isso não implica suporte IDEX/toolchanger.

[Voltar ao README](README.md)
