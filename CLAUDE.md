## OBJETIVO DA APLICAÇÃO

O objetivo dessa aplicação é o treinamento e inferencia de um modelo de Visão Computacional capaz de fazer mapeamento de poses de um corpo humano captado via webcam em tempo real. Sua função é tranbsmitir os 17 pontos de rastreios pegos pelo YOLO26 e enviar via UDP para um ambiente no motor de jogos Unity. 

O sistema vai se concentrar no script: "pose_YOLO_real_time.py"

## ESTRUTURA

- `pose_YOLO_real_time.py`: YOLO26-pose (17 pontos COCO, 2D) + mãos do MediaPipe (em paralelo) -> Unity
- `pose_MEDIAPIPE_real_time.py`: MediaPipe (33 pontos 3D + mãos + rosto) -> Unity
- `rastreamento/` (pacote compartilhado pelos DOIS scripts; dentro dele os imports são relativos):
  - `envio_unity.py`: formato JSON único e envio UDP (YOLO convertido para os 33 pontos + pseudo-3D: metros pela largura dos ombros e z estimado pelo encurtamento dos ossos)
  - `pontos_pose.py`: enums dos pontos (PontoCOCO, PontoMediaPipe, PontoMao) e a conversão COCO -> MediaPipe
  - `maos_mediapipe.py`: mãos (detector, associação mão <-> pulso, filtro, desenho)
  - `filtros_pose.py`: pré-processamento de pouca luz (CLAHE), filtro por confiança e One Euro
- `ferramentas/udp_test_receiver.py`: receptor UDP de teste (sem o Unity)
- `models/`: todos os modelos (MediaPipe `.task` + `yolo26n-pose.pt`), fora do git, baixados na primeira execução
- `docs/`: imagens (`docs/Images/`: mapa dos pontos e prints de medições), guia de ajuste do One Euro (`ajuste_one_euro.md`), descrições de PRs (`docs/PRs/`) e gravações de tela (`docs/gravacoes/`, fora do git)
- `setup.bat` (cria o .venv) e `run_sender.bat` (roda MediaPipe, ou YOLO com `run_sender.bat yolo`)
- Projeto Unity oficial: `../UnityBodyTracking` (repositório git separado). Receptor: `PoseUdpReceiver.cs`
- A suavização fica no Unity (`HumanoidAvatarDriver.cs`); nos scripts Python, `SUAVIZAR = False`

## REGRAS DE SEGURANÇA

1. Não é permitido criação ou modificações de códigos de forma automática sem me perguntar antes
2. É necessário que seja mencionado para mim antes de perguntar se pode criar/modificar/deletar algo no código e onde exatamente e o porquê
3. Seu principal objetivo é fazer a análise do código e aconselhar os principais caminhos e responder dúvidas que eu queira perguntar para resolver alguma coisa no sistema 