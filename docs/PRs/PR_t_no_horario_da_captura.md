# PR: o campo `"t"` da mensagem passa a ser o horário da captura da câmera

**Repositório:** `python` (este)
**Data:** 2026-11-23
**Status:** código alterado e compilando (`py_compile`); falta rodar com a webcam e o Unity
**Depende de:** [PR_one_euro_dt_pelo_horario_do_python.md](PR_one_euro_dt_pelo_horario_do_python.md) (Unity)

## Resumo

Continuação do PR do Unity, que passou a calcular o `dt` do One Euro pela diferença entre os `"t"` de dois
pacotes. Para esse `dt` ser o intervalo real entre os quadros da câmera, o `"t"` tem que ser pego logo depois do
`cap.read()`. Antes ele era pego depois da inferência, que leva um tempo diferente a cada quadro.

Vale para os dois scripts: `pose_YOLO_real_time.py` e `pose_MEDIAPIPE_real_time.py`.
**O formato da mensagem não muda**: o campo continua se chamando `"t"`, em segundos. O Unity não precisa de nenhum ajuste.

## O problema que foi corrigido

O One Euro calcula a velocidade de cada ponto como `(posição_nova - posição_anterior) / dt`. O `dt` certo é o
intervalo entre os momentos em que as duas poses **aconteceram**, ou seja, entre as capturas da câmera.

Antes, o `"t"` era pego depois do processamento:

| Script | Onde o `"t"` era pego |
|---|---|
| YOLO | depois da inferência do corpo **e** da espera pela thread das mãos (`tarefa_maos.result()`) |
| MediaPipe | dentro de `montar_mensagem`, depois de corpo, mãos e rosto |

Então o `"t"` era `captura + tempo de processamento`. Como esse tempo varia de um quadro para outro, a variação
entrava direto no `dt`. Exemplo:

| | Captura | Processamento | `"t"` antigo |
|---|---|---|---|
| Quadro 1 | 0 ms | 20 ms | 20 ms |
| Quadro 2 | 33 ms | 35 ms | 68 ms |

O Unity calculava `dt = 48 ms` no lugar de 33 ms e subestimava a velocidade em ~30% naquele quadro. O cutoff do
filtro oscilava de quadro a quadro, e a suavização ficava irregular.

Este erro é menor que o corrigido no PR do Unity (poucos ms contra 10 a 25 ms), mas some do mesmo jeito.
Ele é maior nos quadros em que as mãos ou o rosto demoram mais para ser detectados.

## O que mudou

### 1. `pose_YOLO_real_time.py`

- **Novo:** `tempo_captura = time.time()` logo depois do `video.read()` dar certo, antes do espelhamento e do pré-processamento.
- **`"t"` da mensagem** e o `t` do `filtro_keypoints` / `rastreador_maos` passam a usar `tempo_captura` (`agora = tempo_captura`).
- **Timestamp do MediaPipe das mãos** (`tempo_ms` do `detect_for_video`) também passa a vir de `tempo_captura`, mantendo a regra de "sempre crescente" (`max(..., ultimo_tempo_ms + 1)`).

### 2. `pose_MEDIAPIPE_real_time.py`

- **Novo:** `tempo_captura = time.time()` logo depois do `camera.read()` dar certo.
- **`montar_mensagem`** ganhou o parâmetro `tempo_captura`, usado no `"t"` e nos filtros (`FILTRO_CORPO_*`, `RASTREADOR_MAOS`) no lugar do `time.time()` interno.
- **Timestamp do MediaPipe** (`tempo_ms` de corpo, mãos e rosto) também passa a vir de `tempo_captura`.

**Por que o timestamp do MediaPipe também:** o `detect_for_video` usa esse horário no rastreamento interno entre
quadros. Antes ele também era pego depois do espelhamento, do CLAHE e da conversão para RGB. Agora o modelo e o
Unity veem o mesmo horário, o da captura.

## O que não muda

- Formato do JSON e nome do campo (`"t"`, segundos, 3 casas decimais).
- Unity (`PoseUdpReceiver.cs`, `HumanoidAvatarDriver.cs`, `AvatarFaceDriver.cs`).
- O One Euro do Python continua desligado (`SUAVIZAR = False`). Se for ligado para testes, ele também passa a usar o horário da captura.
- A medição de FPS e de tempo de inferência mostrada na janela.

## Como verificar

- [ ] `run_sender.bat yolo` e `run_sender.bat` (MediaPipe) rodam sem erro.
- [ ] `ferramentas/udp_test_receiver.py`: o `"t"` continua chegando, sempre crescente, com intervalos perto de 1/FPS da câmera (ex.: ~0,033 s a 30 FPS) e mais regulares que antes.
- [ ] No Unity, parado na frente da webcam: o avatar fica pelo menos tão estável quanto com o PR anterior.
- [ ] Mãos (YOLO e MediaPipe) e rosto (MediaPipe) continuam sendo detectados normalmente.

## Limitações

- **Não é o instante exato do sensor.** O driver da webcam tem um buffer, então o quadro foi tirado um pouco antes do `cap.read()` devolver. Esse atraso costuma ser quase constante, e se cancela na diferença entre dois `"t"`. O `CAP_PROP_POS_MSEC` do OpenCV não é confiável em webcams, por isso não foi usado.
- **`time.time()` pode saltar** se o relógio do Windows for ajustado (NTP). Nesse caso o Unity já cai para a hora de chegada no pacote seguinte (`OneEuroFilter.PacketDt` rejeita `dt <= 0` ou `>= 0,5 s`).

## Arquivos alterados

| Arquivo | Tipo |
|---|---|
| `pose_YOLO_real_time.py` | alterado (`tempo_captura` no laço) |
| `pose_MEDIAPIPE_real_time.py` | alterado (`tempo_captura` no laço + parâmetro novo em `montar_mensagem`) |
