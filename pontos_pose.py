"""
Índices dos pontos de cada modelo e a conversão entre eles
==========================================================

  - PontoCOCO      : os 17 pontos do YOLO26-pose (padrão COCO)
  - PontoMediaPipe : os 33 pontos do corpo do MediaPipe Pose (é o formato que o Unity espera)
  - PontoMao       : os 21 pontos de cada mão do MediaPipe Hand Landmarker
  - COCO_PARA_MEDIAPIPE : em qual posição do MediaPipe entra cada ponto do COCO

"Esquerdo" e "direito" são sempre da PESSOA (não de quem olha a imagem), nos dois modelos.
Os nomes batem com os enums PoseLandmark / HandLandmark do PoseUdpReceiver.cs no Unity.
"""

from enum import IntEnum


class PontoCOCO(IntEnum):
    """Os 17 pontos do YOLO26-pose (veja mapa_pontos_yolo26.png)."""
    NARIZ = 0
    OLHO_ESQUERDO = 1
    OLHO_DIREITO = 2
    ORELHA_ESQUERDA = 3
    ORELHA_DIREITA = 4
    OMBRO_ESQUERDO = 5
    OMBRO_DIREITO = 6
    COTOVELO_ESQUERDO = 7
    COTOVELO_DIREITO = 8
    PULSO_ESQUERDO = 9
    PULSO_DIREITO = 10
    QUADRIL_ESQUERDO = 11
    QUADRIL_DIREITO = 12
    JOELHO_ESQUERDO = 13
    JOELHO_DIREITO = 14
    TORNOZELO_ESQUERDO = 15
    TORNOZELO_DIREITO = 16


class PontoMediaPipe(IntEnum):
    """Os 33 pontos do MediaPipe Pose (PoseLandmark no Unity)."""
    NARIZ = 0
    OLHO_ESQUERDO_INTERNO = 1
    OLHO_ESQUERDO = 2
    OLHO_ESQUERDO_EXTERNO = 3
    OLHO_DIREITO_INTERNO = 4
    OLHO_DIREITO = 5
    OLHO_DIREITO_EXTERNO = 6
    ORELHA_ESQUERDA = 7
    ORELHA_DIREITA = 8
    BOCA_ESQUERDA = 9
    BOCA_DIREITA = 10
    OMBRO_ESQUERDO = 11
    OMBRO_DIREITO = 12
    COTOVELO_ESQUERDO = 13
    COTOVELO_DIREITO = 14
    PULSO_ESQUERDO = 15
    PULSO_DIREITO = 16
    MINDINHO_ESQUERDO = 17
    MINDINHO_DIREITO = 18
    INDICADOR_ESQUERDO = 19
    INDICADOR_DIREITO = 20
    POLEGAR_ESQUERDO = 21
    POLEGAR_DIREITO = 22
    QUADRIL_ESQUERDO = 23
    QUADRIL_DIREITO = 24
    JOELHO_ESQUERDO = 25
    JOELHO_DIREITO = 26
    TORNOZELO_ESQUERDO = 27
    TORNOZELO_DIREITO = 28
    CALCANHAR_ESQUERDO = 29
    CALCANHAR_DIREITO = 30
    PONTA_PE_ESQUERDO = 31
    PONTA_PE_DIREITO = 32


class PontoMao(IntEnum):
    """Os 21 pontos de cada mão do MediaPipe Hand Landmarker (HandLandmark no Unity)."""
    PULSO = 0
    POLEGAR_CMC = 1
    POLEGAR_MCP = 2
    POLEGAR_IP = 3
    POLEGAR_PONTA = 4
    INDICADOR_MCP = 5
    INDICADOR_PIP = 6
    INDICADOR_DIP = 7
    INDICADOR_PONTA = 8
    MEDIO_MCP = 9
    MEDIO_PIP = 10
    MEDIO_DIP = 11
    MEDIO_PONTA = 12
    ANELAR_MCP = 13
    ANELAR_PIP = 14
    ANELAR_DIP = 15
    ANELAR_PONTA = 16
    MINDINHO_MCP = 17
    MINDINHO_PIP = 18
    MINDINHO_DIP = 19
    MINDINHO_PONTA = 20


N_PONTOS_COCO = len(PontoCOCO)            # 17
N_PONTOS_MEDIAPIPE = len(PontoMediaPipe)  # 33
N_PONTOS_MAO = len(PontoMao)              # 21


# Cada ponto do COCO entra na posição de mesmo nome do MediaPipe.
# Os pontos do MediaPipe que o COCO não tem (cantos dos olhos, boca, dedos, calcanhares,
# pontas dos pés) ficam com visibilidade 0, e o Unity os ignora.
COCO_PARA_MEDIAPIPE = {ponto: PontoMediaPipe[ponto.name] for ponto in PontoCOCO}
