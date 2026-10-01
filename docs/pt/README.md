# KACE

🌐 [English](../../README.md) · [Español](../../docs/es/README.md) · [Português](../../docs/pt/README.md)

![KACE](../../docs/assets/kace_banner.png)

KACE é a CLI em Python executada no host da impressora para preparar, revisar e implantar configurações Klipper e artefatos de firmware MCU. [KACE Studio](https://github.com/3D-uy/KACE-studio/blob/main/docs/pt/README.md) prepara o Raspberry Pi pelo Windows e oferece SSH/SFTP; KACE mantém a autoridade sobre configuração e instalação.

**Pré-1.0; qualificação controlada.** [VERSION](../../VERSION) declara a versão e [CHANGELOG](../../CHANGELOG.md) descreve o candidato atual. Alterações de código sem commit não fazem parte do instalador fixado. A validação automática não certifica hardware físico nem uma release estável.

## Início rápido

Requer Linux/Raspberry Pi, Python 3.11+, Git, rede para dependências e as permissões necessárias ao fluxo escolhido. Docker/toolchains só são necessários nos fluxos documentados de compilação e validação.

Para um Pi novo, use **KACE Studio**. Para um host Linux existente, o instalador abaixo verifica sua identidade imutável antes da execução. Revise antes de usar: ele instala a revisão fixada, que pode diferir do código que você está lendo.

```bash
KACE_COMMIT='b7988b57b5fc80fbc55c3d1326768289dbccb179'
KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" &&
printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - &&
KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

Para executar o checkout atual do código:

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Também é possível preparar o host manualmente: no Raspberry Pi Imager selecione o Pi exato e um SO compatível, armazenamento de destino, hostname, usuário, rede e SSH; revise e confirme a gravação destrutiva. Ejete com segurança, inicie o Pi e conecte pelo hostname ou IP atribuído pelo roteador. Instale KACE nele com o comando verificado acima. Preparar o SO não configura nem calibra a impressora.

## 🧭 Uso

1. Execute `kace` após instalar, ou `python kace.py` no ambiente de código ativado. Escolha idioma e nível de experiência.
2. Selecione placa/MCU exata, geometria, motores, probes e outros recursos suportados; revise pinos e requisitos elétricos.
3. Revise os artefatos em `~/kace/`. Siga o procedimento de entrega do firmware e a verificação de identidade física.
4. Revise o diff da configuração e os ajustes preservados, aceite aplicação/ativação e aguarde a conclusão verificada. Moonraker local no Pi usa `127.0.0.1:7125`.
5. Verifique sensores, endstops, movimento e aquecimento separadamente com o guia de hardware. Em caso de interrupção, siga o checkpoint e as instruções de recuperação.

## ⚠️ Escopo e limites

- Há fluxos Cartesian/CoreXY; encontrar um perfil upstream não garante compatibilidade. Firmware runtime, provisório, somente preparação e somente configuração são categorias distintas.
- Telas desconhecidas, circuitos obrigatórios não suportados e dependências de perfis não revisadas continuam bloqueados. Consulte [escopo](../../docs/en/SUPPORT_SCOPE.md) e [telas](../../docs/pt/DISPLAYS.md).
- Não salve alterações pelo Mainsail/SSH durante a publicação. A gravação local usa locks cooperativos e substituição atômica por arquivo, não uma transação do diretório inteiro contra editores externos. Planos remotos alterados e substituição de arquivos existentes podem exigir propostas manuais.
- O rollback preserva alterações atuais e snapshots duráveis quando não é possível provar uma restauração segura. `Ready` não basta: ativação e evidência de artefatos e firmware continuam necessárias.
- A responsabilidade cobre a instalação inicial e suas retomadas pendentes até `DONE`/`COMPLETE`; não há promessa de monitoramento ou revalidação de edições posteriores do usuário.

## 🛠️ Desenvolvimento

Consulte [Desenvolvimento (EN)](../../docs/DEVELOPMENT.md) para arquitetura, contribuição e testes. Execute primeiro a regressão específica e depois os gates afetados. A suíte completa inclui funções pytest não coletadas pelo unittest. Nunca atualize snapshots apenas para fazer um teste passar.

## 📚 Documentação

| Necessidade | Guia |
| --- | --- |
| Desenvolvimento, arquitetura e testes (EN) | [DEVELOPMENT.md](../DEVELOPMENT.md) |
| Implantação e recuperação (EN) | [DEPLOYMENT.md](../../docs/en/DEPLOYMENT.md) |
| Qualificação de hardware (EN) | [HARDWARE_TESTING.md](../../docs/HARDWARE_TESTING.md) |
| Escopo (EN) | [SUPPORT_SCOPE.md](../../docs/en/SUPPORT_SCOPE.md) |
| Telas | [DISPLAYS.md](../../docs/pt/DISPLAYS.md) |
| Release (EN) | [RELEASE.md](../../docs/RELEASE.md) |
| Código de conduta (EN) | [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Notas do candidato atual | [CHANGELOG.md](../../CHANGELOG.md) |
| Segurança (EN) | [SECURITY.md](../../SECURITY.md) |

## Licença

[GPL-3.0](../../LICENSE).
