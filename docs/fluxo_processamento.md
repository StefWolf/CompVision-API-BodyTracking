# Fluxo de processamento: da webcam ao avatar no Unity

Este documento explica, etapa por etapa, o caminho de um quadro da webcam até o movimento do avatar.
A numeração segue o fluxograma abaixo.

![Fluxograma do processamento](Images/fluxograma_processamento.png)

## Visão geral

O sistema tem duas partes que conversam pela rede:

| Parte | Onde roda | Papel |
|---|---|---|
| **Python** | PC com a webcam | Captura a imagem, detecta o corpo (YOLO26-pose **ou** MediaPipe) e as mãos, e envia os pontos |
| **Rede (UDP)** | PC → Unity | Uma mensagem JSON por quadro, na porta 5052 |
| **Unity** | Editor no PC (Meta Quest via cabo Link) ou app instalado no Meta Quest 3S | Suaviza os pontos (One Euro) e transforma em rotações dos ossos do avatar |

Os dois modelos de visão computacional são **alternativos**: roda um script ou o outro. Os dois produzem
**o mesmo formato de mensagem**, então o Unity não precisa saber qual está rodando.

| | `pose_YOLO_real_time.py` | `pose_MEDIAPIPE_real_time.py` |
|---|---|---|
| Corpo | YOLO26n-pose: 17 pontos 2D (padrão COCO) | Pose Landmarker: 33 pontos 3D em metros |
| Mãos | MediaPipe Hand Landmarker (21 pontos por mão), em paralelo | MediaPipe Hand Landmarker |
| Rosto | não tem | Face Landmarker: 52 expressões (blendshapes) |
| Como rodar | `run_sender.bat yolo` | `run_sender.bat` |

---

## Parte 1: Python (PC)

### 1. Captura

- A webcam é lida pelo OpenCV (`cap.read()`), em 640×480.
- **Logo depois da leitura**, o script grava o horário da captura (`time.time()`). Ele vai no campo `"t"` da
  mensagem.
  - **Por que aqui:** no Unity, o filtro One Euro usa a diferença entre dois `"t"` como intervalo entre quadros
    (`dt`). Se o horário fosse pego depois da inferência, o tempo de processamento, que varia de um quadro para
    outro, entraria no `dt`.
- O espelhamento da imagem fica **desligado** (`ESPELHAR = False`). Em primeira pessoa, no VR, a mão direita do
  usuário precisa mover a mão direita do avatar. Com a imagem espelhada, os lados se invertem e os braços cruzam.

### 2. Pré-processamento (pouca luz)

Arquivo: `rastreamento/filtros_pose.py` (`pre_processar`).

1. Mede o **brilho médio** do quadro (0 a 255).
2. Se o brilho estiver abaixo de **90** (ambiente escuro), aplica o **CLAHE**:
   - CLAHE é uma equalização de histograma adaptativa: realça o contraste em pequenas regiões (grade 8×8) e
     limita o ganho (clip 2,0) para não amplificar ruído;
   - é aplicado só no canal **L** (luminosidade) do espaço de cor **LAB**, então a imagem clareia sem mudar as cores .
3. Se o ambiente estiver claro, o quadro segue sem mudanças.

Para os modelos do MediaPipe, a imagem também é convertida de BGR (padrão do OpenCV) para RGB.

### 3. Inferência

**3a. YOLO26n-pose** (`pose_YOLO_real_time.py`)

- Detecta **17 pontos** do corpo (nariz, olhos, orelhas, ombros, cotovelos, pulsos, quadris, joelhos, tornozelos),
  em **pixels**, cada um com uma **confiança** de 0 a 1.
- **Em paralelo**, numa segunda thread, o MediaPipe Hand Landmarker detecta as mãos (21 pontos por mão). Assim o
  tempo das mãos não soma ao tempo do corpo.

**3b. MediaPipe** (`pose_MEDIAPIPE_real_time.py`)

Três modelos rodam em paralelo sobre o mesmo quadro:

- **Pose Landmarker:** 33 pontos do corpo, já em **3D e em metros** (centro no quadril), com visibilidade.
- **Hand Landmarker:** 21 pontos por mão.
- **Face Landmarker:** 52 expressões do rosto (abrir a boca, piscar, sorrir...). (NÃO TO USANDO)

### 4. Filtragem e conversão

Arquivos: `rastreamento/filtros_pose.py`, `rastreamento/envio_unity.py`, `rastreamento/maos_mediapipe.py`.

**Filtro por confiança (os dois modelos)**
- Só são aceitos pontos com confiança (YOLO) ou visibilidade (MediaPipe) **≥ 0,5**.
- Um ponto que some repete o **último valor bom por até 5 quadros**. Isso evita que uma falha de um quadro só faça
  o membro do avatar "cair" para a pose de repouso.

**Conversão do YOLO para o formato do MediaPipe (`ConversorCOCO`)**
- Os **17 pontos COCO** são colocados nas posições correspondentes dos **33 pontos** do MediaPipe. Os pontos que o
  YOLO não tem (dedos do corpo, calcanhares e pontas dos pés) vão com visibilidade 0.
- **Pixels → metros:** a escala vem da largura dos ombros (0,36 m de um adulto médio) e da altura do tronco
  (0,50 m). Usa a maior das duas estimativas, porque girar o corpo só encurta as medidas na imagem. A escala muda
  aos poucos, para o corpo não "pulsar" de tamanho.
- **Centro no quadril**, igual ao MediaPipe.
- **Profundidade (z) estimada pelo encurtamento dos ossos:** se um osso do braço ou da perna aparece mais curto na
  imagem do que o seu comprimento real, ele está apontando para a câmera. A profundidade é
  `√(L² − l²)`, onde `L` é o comprimento real e `l` o comprimento na imagem.

**Mãos ligadas ao pulso certo**
- Cada mão detectada é associada ao pulso do corpo mais próximo (`"lh"` = pulso esquerdo, `"rh"` = pulso direito).
  Uma mão a mais de 0,2 do tamanho da imagem (em coordenadas de 0 a 1) do pulso é descartada (provavelmente é de outra pessoa ou um erro).

**Suavização no Python: desligada**
- Os scripts têm um filtro One Euro, mas ele fica desligado (`SUAVIZAR = False`). A suavização é feita só no Unity
  (veja a etapa 9). Suavizar nos dois lados somaria o atraso.

### 5. Mensagem JSON

Os dois scripts montam a mesma mensagem (`nova_mensagem` em `envio_unity.py`):

```json
{
  "src": "yolo",              // ou "mediapipe": qual modelo gerou a mensagem
  "frame": 1234,              // número do quadro
  "t": 1764090000.123,        // horário da captura, em segundos
  "detected": true,           // false = ninguém na imagem
  "w": 640, "h": 480,         // tamanho da imagem
  "lm":  [x, y, z, vis, ...], // 33 pontos do corpo na imagem (0 a 1) + visibilidade
  "wlm": [x, y, z, ...],      // 33 pontos do corpo em metros
  "lh":  [x, y, z, ...],      // mão esquerda: 21 pontos em metros, a partir do pulso
  "rh":  [x, y, z, ...],      // mão direita
  "fbs": [...]                // 52 expressões do rosto (só MediaPipe)
}
```

---

## Parte 2: Rede

Arquivo: `rastreamento/envio_unity.py` (`EnviadorUnity`).

- **Protocolo:** UDP, porta **5052**, **um datagrama JSON por quadro**.
  - **Por que UDP:** em tempo real, um pacote atrasado não serve mais. O UDP não espera reenvio, então a pose mais
    nova sempre passa na frente.
- **Descoberta automática:** o Python não precisa saber o IP do Unity.
  1. O Unity avisa "estou aqui" a cada 1 s (porta 5053).
  2. O PC avisa "sou o PC das poses" por broadcast.
  3. O PC passa a enviar as poses **direto** para o IP de cada Unity que se apresentou nos últimos 3 s.
- **Destinos possíveis:** `127.0.0.1` (Unity no mesmo PC, com o Quest pelo cabo Link) ou o IP do Meta Quest na rede
  Wi-Fi (app instalado no headset).

---

## Parte 3: Unity

Scripts em `UnityBodyTracking/Assets/Scripts/PoseTracking/`.

### 6. Recepção (`PoseUdpReceiver.cs`)

- Uma **thread própria** escuta a porta 5052, para a recepção não depender da taxa de quadros do jogo.
- O JSON vira um objeto `PoseMessage` (`JsonUtility`). O Unity sempre usa a mensagem mais recente.
- **Sem pacotes por 0,5 s:** considera que não há pessoa, e o avatar volta aos poucos para a pose de repouso.

### 7. Intervalo entre quadros (dt)

Arquivo: `OneEuroFilter.cs` (`PacketDt`).

- **dt = t<sub>atual</sub> − t<sub>anterior</sub>**, usando o horário gravado pelo Python. Assim o dt é o intervalo
  real entre as capturas da câmera.
- **Por que não a hora de chegada no Unity:**
  - a chegada é arredondada para o frame do Unity (no Quest a 72 Hz, um intervalo de 33 ms vira 28 ou 42 ms);
  - na rede Wi-Fi os pacotes podem chegar em rajada (dois quase juntos).
  Os dois erros fazem o filtro calcular velocidades erradas e deixar o tremor passar.
- **Plano B:** volta para a hora de chegada no primeiro pacote, quando o Python é reiniciado ou trocado de modelo
  (`"t"` volta no tempo) e em pausas de 0,5 s ou mais.

### 8. Espaço do avatar e fonte das mãos

- **Giro de 180° em Y:** os pontos chegam com a pessoa olhando para a câmera (−Z), e o avatar olha para +Z.
- **`HandTrackingSource.cs`** escolhe de onde vêm as mãos:

| Modo | Fonte |
|---|---|
| Webcam | só o MediaPipe (UDP) |
| XR Hands | só o rastreamento de mãos do Meta Quest |
| Automático | o Quest quando ele vê a mão; a webcam quando a mão sai da visão do headset, com transição suave |

### 9. Pós-processamento: filtro One Euro

Arquivo: `OneEuroFilter.cs`, usado pelo `HumanoidAvatarDriver.cs` e pelo `AvatarFaceDriver.cs`.

Os pontos que vêm do modelo **tremem** um pouco de um quadro para outro, mesmo com a pessoa parada. Um filtro comum
(média móvel) tira o tremor, mas deixa o movimento atrasado. O **One Euro** (Casiez et al., 2012) resolve isso
**mudando a intensidade da suavização conforme a velocidade**:

```
cutoff = minCutoff + β · |velocidade|
τ      = 1 / (2π · cutoff)
α      = 1 / (1 + τ / dt)
x̂     ← x̂ + α · (x − x̂)
```

- `x` é o ponto novo, `x̂` o ponto suavizado, `α` (0 a 1) o quanto o ponto suavizado anda em direção ao novo.
- **Parado** (velocidade ≈ 0): o cutoff fica baixo, `α` pequeno → suaviza bastante e **tira o tremor**.
- **Movimento rápido:** o cutoff sobe, `α` perto de 1 → quase não suaviza e **não atrasa**.
- A própria velocidade é suavizada (a 1 Hz), para o tremor não ser confundido com movimento.

| Onde é aplicado | `minCutoff` | `β` |
|---|---|---|
| 33 pontos do corpo, quadril e pontos das mãos | 1,5 | 5 |
| Orientação da cabeça | 1,5 | 5 × 0,2 = 1 |
| Expressões do rosto (MediaPipe) | 2 | 1 |

Os valores são ajustáveis no Inspector. Veja o guia de testes em [ajuste_one_euro.md](ajuste_one_euro.md).

**Por que a suavização fica no Unity e não no Python:**
1. As mãos podem vir da fusão webcam + headset; o filtro roda depois da fusão e suaviza também a troca de fonte.
2. No Unity os pontos já estão em metros, igual para os dois modelos (no Python o YOLO está em pixels).
3. Um só lugar para ajustar, com o jogo rodando.
4. O filtro também absorve a irregularidade da rede.

### 10. Ossos do avatar (`HumanoidAvatarDriver.cs`)

Os pontos suavizados viram **rotações dos ossos** de um avatar Humanoid do Unity:

- **Tronco:** quadril e peito pela linha dos quadris, linha dos ombros e direção do tronco.
- **Braços:** IK de dois ossos (braço e antebraço) do ombro até o pulso, com o cotovelo indicando para que lado dobrar.
- **Mãos e dedos:** orientação da palma e dedos pelos 21 pontos da mão.
- **Pernas e cabeça.**
- **Partes pouco visíveis** (visibilidade < 0,5) voltam aos poucos para a pose de repouso, em vez de tremer.
- **Rosto** (`AvatarFaceDriver.cs`): as 52 expressões do MediaPipe viram blendshapes da malha do avatar.

### 11. Modo VR, opcional (`VRAvatarRig.cs`)

Usado quando o usuário está com o Meta Quest e "é" o avatar em primeira pessoa:

- **Cabeça e posição** do avatar seguem o headset (os olhos do avatar ficam na câmera do headset).
- **Braços** vão até os pulsos que o Quest rastreia; o cotovelo da webcam vira só a dica de dobra.
- **Calibração:** a frente do avatar passa a ser a direção da webcam e a altura dele igual à do usuário. Acontece
  ao abrir o app, ao recentralizar o Quest e na tecla V (no PC).

### 12. Avatar animado

O resultado é o avatar repetindo o movimento do corpo do usuário em tempo real, no Editor do Unity ou no app
instalado no Meta Quest 3S.

---

## Limitações conhecidas

- **Taxa da câmera:** a webcam atual do notebook entrega ~15 FPS (medido pelo campo `"t"`). Uma webcam melhor
  deixa o movimento mais fluido.
- **YOLO é 2D:** a profundidade é estimada e tem ambiguidade de sinal (o osso pode estar apontando para a câmera ou
  para trás; o sistema assume para a câmera). O giro do tronco quando o usuário fica de lado é limitado.
- **Filtros do corpo não são zerados** quando a pessoa sai do quadro e volta: o avatar pode "deslizar" da posição
  antiga. Proposta em [PRs/PR_zerar_filtros_do_corpo.md](PRs/PR_zerar_filtros_do_corpo.md).
