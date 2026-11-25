# Ajuste do One Euro no Unity: valores de `minCutoff` e `beta` para testar (YOLO e MediaPipe)

**Onde:** componente `HumanoidAvatarDriver` no avatar, seção **"Suavização (filtro One Euro)"** do Inspector.
**Valores atuais:** `minCutoff = 1,5` e `beta = 5` (iguais para os dois modelos).
**Data:** 2026-11-25

## Antes de começar: 5 avisos

1. **O que você muda no Inspector durante o Play é perdido quando o Play para.** Anote o valor bom na tabela
   de resultados antes de parar. Outra opção: ⋮ do componente → *Copy Component*, parar o Play e
   *Paste Component Values*.
2. **Não existe um ajuste por modelo.** O driver tem um só par `minCutoff`/`beta`. Para comparar YOLO e
   MediaPipe, troque o script do Python (`run_sender.bat yolo` / `run_sender.bat`) e mude os valores à mão.
   Se os melhores valores dos dois modelos ficarem bem diferentes, dá para criar um ajuste por modelo depois
   (o campo `"src"` da mensagem diz de onde ela veio).
3. **O mesmo par vale para mais de um filtro:**
   - os 33 pontos do corpo (`poseFilters`);
   - o quadril horizontal (`hipXFilter`, com `followHorizontal`);
   - os dedos das mãos da **webcam** (`handFilters`);
   - a orientação da cabeça, que usa `beta × 0,2`.

   O rosto (`AvatarFaceDriver`, só no MediaPipe) tem os seus próprios valores (2 / 1) e não entra neste teste.
4. **`MIN_CUTOFF` e `BETA` no topo dos scripts do Python não têm relação com estes.** Eles só valem com
   `SUAVIZAR = True` e estão em outra unidade (pixels). Deixe `SUAVIZAR = False`.
5. **Não use "sair do quadro e voltar" para julgar os valores.** Os filtros do corpo ainda não são zerados
   (veja [PR_zerar_filtros_do_corpo.md](PRs/PR_zerar_filtros_do_corpo.md)), então o deslize ao voltar
   acontece com qualquer valor.

## Como os dois números funcionam

A cada pacote, o filtro decide o quanto segue o ponto novo usando um **cutoff** (em Hz):

```
cutoff = minCutoff + beta × velocidade do ponto (m/s)
```

- **`minCutoff`** define o comportamento **parado**. Menor = mais estável, porém mais "atrasado".
- **`beta`** define o quanto o filtro **se solta quando o ponto se move**. Maior = menos atraso em
  movimentos rápidos, porém deixa passar mais tremor.

Cada `minCutoff`, com o ponto parado e a 30 FPS:

| `minCutoff` | Atraso típico parado | Quanto o ponto anda em direção ao valor novo a cada quadro |
|---|---|---|
| 0,3 | ~530 ms | 6% (muito estável, "boiando") |
| 0,5 | ~320 ms | 9% |
| 0,8 | ~200 ms | 14% |
| 1,0 | ~160 ms | 17% |
| 1,5 | ~105 ms | 24% (atual) |
| 2,0 | ~80 ms | 30% |
| 3,0 | ~55 ms | 39% (quase sem suavização) |

Velocidades de referência para o `beta`:
- **~0,1 m/s:** tremor do ponto parado ou movimento bem lento;
- **~1 m/s:** braço em movimento normal;
- **~3 m/s:** aceno ou soco rápido.

> A velocidade usada pelo filtro também é suavizada (a 1 Hz, valor fixo no código). Por isso, no começo de
> um movimento rápido, o `beta` demora ~0,1 a 0,2 s para "acordar". Esse pequeno atraso inicial existe com
> qualquer `beta`.

## Diferença entre os modelos (por que os pontos de partida são diferentes)

| | YOLO (`pose_YOLO_real_time.py`) | MediaPipe (`pose_MEDIAPIPE_real_time.py`) |
|---|---|---|
| Pontos | 17 em 2D, convertidos para metros pela largura dos ombros | 33 já em metros (world landmarks) |
| Profundidade (z) | **estimada** pelo encurtamento dos ossos (`_estimar_profundidade`). Perto do limite `FOLGA_PROFUNDIDADE = 0,95`, o z de um punho pode saltar de 0 para ~8 cm de um quadro para outro | vem do modelo; treme, mas sem saltos dessa forma |
| Escala | muda devagar com a distância dos ombros, e o corpo inteiro "respira" um pouco | estável |
| O que esperar | mais ruído parado → precisa de `minCutoff` **menor**; os saltos de z parecem "velocidade" → `beta` **mais baixo**, senão o filtro se solta à toa | ruído menor → tolera `minCutoff` maior e `beta` maior (mais resposta) |

## Procedimento recomendado (o do artigo do One Euro, em 2 fases)

Faça para cada modelo, sempre com os mesmos movimentos.

**Fase 1: achar o `minCutoff` (com `beta = 0`)**
1. Coloque `beta = 0`.
2. Fique **parado** de frente para a webcam por ~10 s, com os braços um pouco abertos.
3. Comece em 3,0 e vá **diminuindo** (3,0 → 2,0 → 1,5 → 1,0 → 0,8 → 0,5 → 0,3) até o tremor parado ficar aceitável.
4. Fique com o **maior** valor que já deixa o avatar estável. Quanto maior, menos atraso.

**Fase 2: achar o `beta` (com o `minCutoff` da fase 1)**
1. Faça **movimentos rápidos**: aceno, soco para frente, levantar e baixar os braços.
2. Vá **aumentando** o `beta` (0,5 → 1 → 2 → 3 → 5 → 8 → 12) até o braço parar de "arrastar" atrás do movimento.
3. Fique com o **menor** valor que já tira o atraso.
4. Volte a ficar parado e confira se o tremor não voltou. Se voltou, desça um passo do `beta`.

## Combinações prontas para testar

Se preferir ir direto às combinações, use estas. A tabela mostra o cutoff (e o atraso aproximado) em 3
velocidades. **São pontos de partida, não valores medidos**: quem decide é o teste.

### YOLO

| ID | `minCutoff` | `beta` | Parado (0,1 m/s) | Normal (1 m/s) | Rápido (3 m/s) | Hipótese |
|---|---|---|---|---|---|---|
| Y0 | 1,5 | 5 | 2,0 Hz · 80 ms | 6,5 Hz · 24 ms | 16,5 Hz · 10 ms | **Atual.** Base de comparação; deve tremer parado |
| Y1 | 1,0 | 4 | 1,4 Hz · 114 ms | 5,0 Hz · 32 ms | 13 Hz · 12 ms | Um passo mais estável, quase o mesmo tempo de resposta |
| Y2 | 0,8 | 3 | 1,1 Hz · 145 ms | 3,8 Hz · 42 ms | 9,8 Hz · 16 ms | **Ponto de partida sugerido para o YOLO** |
| Y3 | 0,5 | 3 | 0,8 Hz · 200 ms | 3,5 Hz · 45 ms | 9,5 Hz · 17 ms | Bem estável parado, ainda responde a movimentos |
| Y4 | 0,5 | 1,5 | 0,65 Hz · 245 ms | 2,0 Hz · 80 ms | 5,0 Hz · 32 ms | Para quando os saltos de z deixam o Y3 tremendo |
| Y5 | 0,3 | 1,5 | 0,45 Hz · 355 ms | 1,8 Hz · 88 ms | 4,8 Hz · 33 ms | Máximo de estabilidade; deve parecer "lento" |
| Y6 | 0,8 | 6 | 1,4 Hz · 114 ms | 6,8 Hz · 23 ms | 18,8 Hz · 8 ms | Mesma estabilidade do Y2 parado, mais resposta |
| Y7 | 1,0 | 2 | 1,2 Hz · 133 ms | 3,0 Hz · 53 ms | 7,0 Hz · 23 ms | Meio-termo com `beta` baixo |

### MediaPipe

| ID | `minCutoff` | `beta` | Parado (0,1 m/s) | Normal (1 m/s) | Rápido (3 m/s) | Hipótese |
|---|---|---|---|---|---|---|
| M0 | 1,5 | 5 | 2,0 Hz · 80 ms | 6,5 Hz · 24 ms | 16,5 Hz · 10 ms | **Atual.** Base de comparação |
| M1 | 1,0 | 5 | 1,5 Hz · 106 ms | 6,0 Hz · 27 ms | 16 Hz · 10 ms | Mais estável parado, mesma resposta: **ponto de partida sugerido** |
| M2 | 2,0 | 5 | 2,5 Hz · 64 ms | 7,0 Hz · 23 ms | 17 Hz · 9 ms | Mais resposta; ver se ainda fica estável |
| M3 | 1,5 | 3 | 1,8 Hz · 88 ms | 4,5 Hz · 35 ms | 10,5 Hz · 15 ms | Menos tremor durante o movimento |
| M4 | 1,5 | 8 | 2,3 Hz · 69 ms | 9,5 Hz · 17 ms | 25,5 Hz · 6 ms | Muito responsivo (bom para gestos rápidos) |
| M5 | 1,0 | 8 | 1,8 Hz · 88 ms | 9,0 Hz · 18 ms | 25 Hz · 6 ms | Estável parado + muito responsivo |
| M6 | 2,0 | 2 | 2,2 Hz · 72 ms | 4,0 Hz · 40 ms | 8,0 Hz · 20 ms | Pouca diferença entre parado e em movimento |
| M7 | 0,8 | 4 | 1,2 Hz · 133 ms | 4,8 Hz · 33 ms | 12,8 Hz · 12 ms | O mais estável parado do grupo |

**Ordem sugerida:** primeiro o atual (Y0/M0); depois o ponto de partida (Y2/M1); depois os vizinhos na
direção que o teste pedir: mais tremor → mais para baixo da tabela; mais atraso → combinações com `beta` maior.

## Roteiro de cada teste (~30 s por combinação)

1. **Parado 10 s:** olhe o tremor nos punhos, cotovelos e joelhos.
2. **Movimento lento:** levantar os braços devagar até a altura dos ombros. Ele deve ser contínuo, sem "degraus".
3. **Movimento rápido:** 3 acenos e 3 socos para frente. O braço não deve arrastar nem passar do ponto.
4. **Mãos (webcam):** abrir e fechar a mão. Os dedos usam os mesmos valores.
5. **Lateral (com `followHorizontal` ligado):** um passo para o lado. O avatar acompanha sem deslizar demais.

## Tabela de resultados (preencher durante os testes)

Notas de 1 (ruim) a 5 (ótimo).

| ID | Modelo | `minCutoff` | `beta` | Tremor parado | Atraso no rápido | Lento contínuo | Dedos | Observações |
|---|---|---|---|---|---|---|---|---|
| Y0 | YOLO | 1,5 | 5 | | | | | |
| Y2 | YOLO | 0,8 | 3 | | | | | |
| | YOLO | | | | | | | |
| | YOLO | | | | | | | |
| M0 | MediaPipe | 1,5 | 5 | | | | | |
| M1 | MediaPipe | 1,0 | 5 | | | | | |
| | MediaPipe | | | | | | | |
| | MediaPipe | | | | | | | |

## Se nenhuma combinação ficar boa

- **YOLO tremendo até com `minCutoff` 0,3:** o ruído provavelmente vem da profundidade estimada e não do
  filtro. Para confirmar, teste com `estimar_profundidade=False` no Python (z = 0). Seria uma mudança de código,
  a ser combinada antes.
- **Dedos tremendo, mas o corpo bom (ou o contrário):** sinal de que as mãos precisam de valores próprios. Hoje
  elas usam o mesmo par do corpo. Separar os dois seria uma mudança no `HumanoidAvatarDriver.cs`.
- **Valores bons bem diferentes entre YOLO e MediaPipe:** criar um ajuste por modelo, escolhido pelo `"src"`
  da mensagem (mudança no `HumanoidAvatarDriver.cs`).
