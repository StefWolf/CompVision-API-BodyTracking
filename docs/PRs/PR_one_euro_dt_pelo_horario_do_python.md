# PR: One Euro do Unity passa a usar o horário do Python (`t`) para calcular o `dt`

**Repositório:** `UnityBodyTracking` (projeto Unity)
**Data:** 2026-11-23
**Status:** código alterado; falta compilar no Unity e validar no Play/headset

## Resumo

A suavização dos pontos (One Euro) continua **no Unity**, que é o lugar certo para ela (veja "Decisão" abaixo).
O que muda é o **`dt`** que o filtro usa: em vez da hora em que o pacote UDP chega no Unity, ele passa a ser
calculado pelo campo `"t"` que o Python já grava em cada mensagem. Assim o filtro vê o intervalo real entre os
quadros da câmera, e o tremor deixa de "escapar" quando a rede (Wi-Fi até o Quest) entrega pacotes em rajada.

Funciona igual para o `pose_YOLO_real_time.py` e para o `pose_MEDIAPIPE_real_time.py` (os dois mandam `"t"`).
**Nenhuma mudança no Python.**

## Decisão: One Euro no Unity, não no Python

- No Python os dois scripts têm o filtro (`rastreamento/filtros_pose.py`), mas com `SUAVIZAR = False`.
- Continua assim. O Unity é o lugar certo porque:
  1. As mãos podem vir da fusão webcam + headset (`HandTrackingSource`); o filtro roda **depois** dessa fusão e suaviza também a troca entre as fontes. O Python não conhece o headset.
  2. O Unity filtra em metros, já no espaço final. No Python o `beta` teria efeitos diferentes no YOLO (pixels) e no MediaPipe (0 a 1).
  3. Um só lugar para ajustar `minCutoff`/`beta` (Inspector, com o jogo rodando), valendo para os dois modelos.
  4. O filtro do Unity também absorve a irregularidade da rede.
  5. Suavizar nos dois lados somaria atraso.

## O problema que foi corrigido

Antes, o `dt` era `Time.unscaledTime` entre dois pacotes **processados** pelo Unity:

1. **Arredondamento para o frame do Unity.** No Quest a 72 Hz (13,9 ms por frame), pacotes da câmera a 30 FPS
   (33 ms) chegavam com `dt` alternando entre ~27,8 ms e ~41,7 ms: erro de ±25% em toda amostra.
2. **Jitter da rede.** Dois pacotes que chegam quase juntos davam `dt = 1/120 s` (8,3 ms) no lugar de 33 ms.
   A velocidade calculada ficava ~4x maior e, com `beta = 5`, o cutoff disparava: o filtro quase não suavizava
   justamente nesse quadro (tremor passando com o usuário parado).

O `"t"` do Python não tem esses dois erros. Ele é gravado ao montar a mensagem (depois da inferência),
então ainda carrega a pequena variação do tempo de inferência, mas é bem mais estável que a hora de chegada.

## O que mudou

### 1. `OneEuroFilter.cs`: novo método `OneEuroFilter.PacketDt`

Arquivo: `Assets/Scripts/PoseTracking/OneEuroFilter.cs`

Calcula o `dt` entre dois pacotes:

- usa `t_atual - t_anterior` (horário do Python), subtraindo em **`double`**. O `t` é o `time.time()`, ~1,7 bilhão de segundos, e em `float` perderia toda a precisão;
- **cai para a hora de chegada (comportamento antigo)** quando o horário do Python não serve:
  - primeiro pacote;
  - `t` voltou no tempo ou não mudou (Python reiniciado, troca YOLO ↔ MediaPipe, ou mensagem sem `"t"`, que vira 0 no `JsonUtility`);
  - intervalo de 0,5 s ou mais (pausa no envio; mesmo valor do timeout padrão do `PoseUdpReceiver`);
- mantém o mínimo de 1/120 s que já existia.

Não precisa de sincronizar o relógio do PC com o do Quest: só a diferença entre dois horários do Python é usada.

### 2. `HumanoidAvatarDriver.cs`: `ReadLandmarks` usa o novo `dt`

Arquivo: `Assets/Scripts/PoseTracking/HumanoidAvatarDriver.cs`

- novo campo `lastSenderTime` (o `"t"` do último pacote);
- o `dt` de `ReadLandmarks` agora vem de `OneEuroFilter.PacketDt`. Ele alimenta os filtros do corpo (`poseFilters`) e do quadril (`hipXFilter`);
- o mesmo valor vai para `udpDt`, usado pelos filtros das **mãos da webcam** (`ReadHands`). Elas melhoram junto;
- **sem mudança** quando as mãos vêm do headset a cada frame (`handsEveryFrame`): ali o `Time.unscaledDeltaTime` continua sendo o certo.

### 3. `AvatarFaceDriver.cs`: mesma correção para as expressões do rosto

Arquivo: `Assets/Scripts/PoseTracking/AvatarFaceDriver.cs`

Tinha o mesmo cálculo de `dt` pela hora de chegada. Agora usa `OneEuroFilter.PacketDt`, com o seu próprio
`lastSenderTime`. Vale só para o MediaPipe (o YOLO não manda rosto).

## Como verificar

- [ ] O projeto compila no Unity sem erros.
- [ ] Com o YOLO e com o MediaPipe, parado na frente da webcam: o avatar treme menos do que antes, principalmente no Quest por Wi-Fi.
- [ ] Movimentos rápidos continuam sem atraso perceptível.
- [ ] Reiniciar o Python (ou trocar de YOLO para MediaPipe) com o Unity rodando não causa salto nem travamento do avatar.
- [ ] As expressões do rosto (MediaPipe) continuam respondendo normalmente.
- [ ] Modo VR com mãos do headset: sem mudança de comportamento.

Dica de ajuste: com o `dt` mais estável, pode ser que `minCutoff`/`beta` do `HumanoidAvatarDriver`
(hoje 1,5 / 5) precisem de um novo ajuste fino no Inspector.

## Limitações e próximos passos

- **`"t"` não era o horário da captura.** Era pego depois da inferência. **Resolvido** em [PR_t_no_horario_da_captura.md](PR_t_no_horario_da_captura.md).
- **Filtros do corpo não são reiniciados quando a pessoa some.** As mãos são (`ReadHands`), mas os `poseFilters` não parecem ser. Ao reaparecer, o avatar pode "deslizar" da posição antiga. Confirmado; proposta em [PR_zerar_filtros_do_corpo.md](PR_zerar_filtros_do_corpo.md).

## Arquivos alterados

| Arquivo | Tipo |
|---|---|
| `Assets/Scripts/PoseTracking/OneEuroFilter.cs` | alterado (método novo `PacketDt`) |
| `Assets/Scripts/PoseTracking/HumanoidAvatarDriver.cs` | alterado (`ReadLandmarks` + campo `lastSenderTime`) |
| `Assets/Scripts/PoseTracking/AvatarFaceDriver.cs` | alterado (`LateUpdate` + campo `lastSenderTime`) |
