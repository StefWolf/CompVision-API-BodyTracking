# PR: Avatar em primeira pessoa no VR (Quest 3S via Link) + mãos do headset no braço + otimização de FPS

**Repositório:** `UnityBodyTracking` (projeto Unity)
**Data:** 2026-11-19
**Status:** testado no Play (FPS); encaixe das mãos ainda precisa ser validado no headset

## Resumo

Primeiro passo do **caso 3** (VR com corpo humanoide inteiro): o usuário com o Quest 3S passa a "ser" o avatar.
O corpo continua vindo da webcam (UDP), a cabeça e a posição vêm do headset, e os braços vão até onde
o Quest vê as mãos. Também foi resolvido o FPS baixo no Unity: de **6 FPS para 70 FPS**.

| Caso de uso | Situação após este PR |
|---|---|
| 1. Corpo inteiro sem headset | Sem mudanças (o novo componente não faz nada no modo `NoHeadset`) |
| 2. VR com avatar só de cabeça e mãos | Ainda não feito. O IK das mãos deste PR será reaproveitado |
| 3. VR com corpo inteiro | Cabeça e posição pelo headset, corpo pela webcam e braços até as mãos do Quest |

## O que mudou

### 1. Novo componente `VRAvatarRig.cs`

Arquivo: `Assets/Scripts/PoseTracking/VRAvatarRig.cs`

Fica no avatar, junto do `HumanoidAvatarDriver`, e roda **depois** dele (`DefaultExecutionOrder(200)`).
A cada frame:

1. **Cabeça igual ao headset.** A rotação da câmera do XR Origin vai para o osso `Head`, e uma parte dela vai para o `Neck` (`neckShare`, 40%).
2. **Avatar ancorado nos olhos.** A raiz do avatar é movida para os olhos dele ficarem na câmera do headset. Se o rig tem os ossos `LeftEye`/`RightEye`, usa os dois; se não tem, usa o `eyeOffset`.
3. **Braços até as mãos do headset.** Quando o Quest vê a mão, o IK do braço é refeito no espaço do mundo, com o **pulso do XR Hands** como alvo:
   - o cotovelo da webcam serve só como dica de para que lado o braço dobra;
   - a orientação da palma e dos dedos, já calculada pelo driver, é preservada;
   - a troca entre a webcam e o headset é suave, usando o peso do `HandTrackingSource` (`blendSeconds`).
4. **Calibração (tecla V, ou automática no primeiro frame).** A direção para onde o headset olha vira a frente do avatar, que deve ser a direção da webcam. Com `matchUserHeight`, o avatar é escalado para a altura dos olhos dele igualar a do usuário.

O headset, o chão do rastreamento e o `HandTrackingSource` são encontrados sozinhos na cena (pelo `XROrigin`).
Por isso, os campos vazios no Inspector são normais.

**Por que fora do `HumanoidAvatarDriver`:** o driver continua igual para o caso 1. O IK das mãos roda
depois que o avatar já está no lugar final, então o alvo (pulso do headset, em coordenadas de mundo) não fica
um frame atrasado em relação ao movimento da cabeça.

### 2. `HandTrackingSource.cs`: novo método `TryGetHeadsetWrist`

Devolve a posição de mundo do pulso vindo do headset para um lado do avatar, respeitando a troca de lados
quando a webcam está espelhada. Nenhuma lógica existente foi alterada.

### 3. Otimização de renderização (6 → 70 FPS)

O Statistics mostrava o gargalo na renderização: render thread em 160 ms, com a thread principal esperando por ela.
O URP estava com as configurações padrão de qualidade alta para PC, caras para VR, porque a cena é renderizada
duas vezes por frame (um olho de cada vez) mais as abas do editor.

`Assets/Settings/PC_RPAsset.asset`:

| Configuração | Antes | Depois |
|---|---|---|
| HDR | ligado | desligado |
| Distância das sombras | 50 m | 15 m |
| Cascatas de sombra | 4 | 2 |
| Sombras suaves | ligadas (qualidade alta) | desligadas |
| Resolução da sombra principal | 2048 | 1024 |
| Sombras de luzes adicionais | ligadas | desligadas |

`Assets/Settings/PC_Renderer.asset`: **SSAO desligado**. Ele recalcula a cena para cada olho.

O que se perde visualmente: sombras com bordas mais duras e bloom mais fraco (sem HDR).

## Configuração necessária para testar

1. **Meta Quest Link (Windows):**
   - OpenXR Runtime ativo = Meta Quest Link;
   - em Beta, **Developer Runtime Features** ligado.
2. **OpenXR, aba Standalone:**
   - **Hand Tracking Subsystem** ligado;
   - perfis de interação: Meta Quest Touch Plus e Hand Interaction.
3. **Cena:**
   - **XR Origin** com Tracking Origin Mode = **Floor**;
   - `HandTrackingSource` criado por **Tools > Pose Tracking > Adicionar fonte de mãos**, com Mode **Automático** e **Webcam Mirrored desmarcado**.
4. **Avatar:**
   - `HumanoidAvatarDriver` com **Drive Head desmarcado**;
   - componente **VR Avatar Rig** adicionado.
5. **Python:** `ESPELHAR = False`. Em primeira pessoa, a mão direita real precisa mover a mão direita do avatar.
6. **Teste:** dê Play, rode o Python, fique de frente para a webcam e aperte **V**.

## Como verificar

- [ ] Olhando para baixo, o corpo do avatar segue o seu.
- [ ] Virando a cabeça, a cabeça do avatar acompanha sem atraso.
- [ ] Com o Quest vendo as mãos, as mãos do avatar ficam em cima das mãos cinza do XR Hands.
- [ ] Ao tirar a mão da vista do Quest, o braço volta suavemente para a pose da webcam.
- [ ] O FPS fica perto de 70 no Statistics.

## Limitações conhecidas

- **Usuário sentado com `matchUserHeight` ligado:** a calibração supõe que o usuário está de pé. Sentado, o avatar encolhe e os braços não alcançam as mãos. Para testar sentado, desmarque a opção.
- **Mão fora do alcance:** se o braço do avatar for mais curto que o do usuário, ele estica até o limite e a mão fica um pouco atrás da real. O braço não estica além do comprimento do modelo.
- **Giro do tronco:** o `pose_YOLO_real_time.py` envia `z = 0`, então o corpo não gira quando o usuário vira de lado para a webcam (a cabeça gira, pelo headset).
- **Agachar:** a cabeça desce pelo headset, mas as pernas vêm da webcam, e os pés podem afundar ou flutuar.
- **Primeira pessoa:** a malha da cabeça do avatar ainda não é escondida da câmera do próprio usuário.
- **Modelo pesado:** `Assets/Character/character.fbx` tem 50 MB, e a cena chega a ~1,1 milhão de triângulos. Uma versão mais leve do modelo deve dar ainda mais folga de FPS.

## Próximos passos

1. Validar o encaixe das mãos no headset.
2. **Caso 2 (VR com cabeça e mãos):** avatar só com cabeça e mãos, reaproveitando o IK deste PR. Falta a calibração webcam ↔ headset, para as mãos da webcam ficarem no lugar certo quando o Quest as perde.
3. Esconder a cabeça do avatar na câmera do próprio usuário.
4. Commitar também as configurações de XR que ainda não estão no git (`Assets/XR`, `Packages/manifest.json`, XRI e samples).
5. Futuro: build nativo no Quest, com o Python enviando UDP pela rede local para o IP do headset.

## Arquivos alterados

| Arquivo | Tipo |
|---|---|
| `Assets/Scripts/PoseTracking/VRAvatarRig.cs` | novo |
| `Assets/Scripts/PoseTracking/HandTrackingSource.cs` | alterado (método novo) |
| `Assets/Settings/PC_RPAsset.asset` | alterado (configurações de renderização) |
| `Assets/Settings/PC_Renderer.asset` | alterado (SSAO desligado) |
