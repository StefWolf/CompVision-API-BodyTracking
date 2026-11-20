"""
Mãos com o MediaPipe Hand Landmarker (usado pelo YOLO e pelo MediaPipe)
=======================================================================

  - baixar_modelo        : baixa um modelo do MediaPipe na primeira vez (sem deixar arquivo corrompido)
  - criar_detector_maos  : cria o detector das duas mãos (modo vídeo)
  - qual_mao_e_qual      : decide qual mão é a "lh" (pulso 15) e qual é a "rh" (pulso 16)
  - RastreadorMaos       : filtra as mãos entre os quadros e coloca na mensagem do Unity
  - desenhar_maos        : desenha os dedos na janela

As mãos vão para a mensagem como "lh"/"rh" (metros, a partir do pulso da mão) e
"lhi"/"rhi" (posição na imagem). O Unity prende cada mão ao pulso do esqueleto, então
funciona igual com o corpo do MediaPipe ou do YOLO.
"""

import urllib.request
from pathlib import Path

import cv2
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from .envio_unity import preencher_mao
from .filtros_pose import FiltroPontos
from .pontos_pose import N_PONTOS_MAO


# =============================================================================
# MODELO
# =============================================================================

PASTA_MODELOS = Path(__file__).resolve().parent.parent / "models"   # python/models
SITE_MODELOS = "https://storage.googleapis.com/mediapipe-models"
ENDERECO_MODELO_MAOS = f"{SITE_MODELOS}/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"


def baixar_modelo(endereco, nome):
    """Baixa o arquivo do modelo na primeira vez e devolve onde ele está salvo."""
    PASTA_MODELOS.mkdir(exist_ok=True)
    arquivo = PASTA_MODELOS / endereco.split("/")[-1]
    if not arquivo.exists():
        print(f"Baixando o modelo de {nome} (só na primeira vez)...")
        # Baixa num arquivo temporário e só renomeia no final: se o download cair no meio,
        # não fica um modelo corrompido com o nome certo (que nunca seria baixado de novo).
        temporario = arquivo.with_name(arquivo.name + ".baixando")
        try:
            urllib.request.urlretrieve(endereco, temporario)
            temporario.replace(arquivo)
        finally:
            temporario.unlink(missing_ok=True)
    return str(arquivo)


def criar_detector_maos(confianca_minima=0.5):
    """Detector das duas mãos, no modo vídeo (usa o quadro anterior para seguir as mãos)."""
    return vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=baixar_modelo(ENDERECO_MODELO_MAOS, "mãos")),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,                               # as duas mãos
        min_hand_detection_confidence=confianca_minima,
        min_hand_presence_confidence=confianca_minima,
        min_tracking_confidence=confianca_minima))


# =============================================================================
# QUAL MÃO É QUAL
# =============================================================================

DISTANCIA_MAXIMA = 0.2   # mão mais longe que isso do pulso (em fração da imagem) é descartada


def distancia(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def qual_mao_e_qual(maos, pulsos):
    """
    Decide qual mão encontrada é a "lh" (presa ao pulso 15) e qual é a "rh" (pulso 16).

    pulsos: {"lh": (x, y), "rh": (x, y)} com os pulsos do CORPO, de 0 a 1 na imagem.
            Um pulso pode ser None (não visto); pulsos=None = corpo não encontrado.

    Jeito principal: cada mão fica com o pulso do corpo mais perto dela na imagem.
    Assim a mão nunca troca de lado no Unity, com a imagem espelhada ou não.
    Se nenhum pulso do corpo foi visto, usa o rótulo "Left"/"Right" do próprio detector de mãos
    (que vem invertido em relação ao corpo, por isso "Right" vira "lh").

    Devolve um dicionário, por exemplo {"lh": 0, "rh": 1} (números das mãos encontradas).
    """
    if maos is None or not maos.hand_landmarks:
        return {}

    pulsos_das_maos = [(m[0].x, m[0].y) for m in maos.hand_landmarks]   # ponto 0 = pulso da mão
    conhecidos = {lado: p for lado, p in (pulsos or {}).items() if p is not None}

    if conhecidos:
        def custo(n, lado):
            return distancia(pulsos_das_maos[n], conhecidos[lado]) if lado in conhecidos else float("inf")

        if len(pulsos_das_maos) >= 2:
            # Testa as duas combinações e fica com a de menor distância total
            jeito_a = custo(0, "lh") + custo(1, "rh")
            jeito_b = custo(1, "lh") + custo(0, "rh")
            if jeito_a == jeito_b == float("inf"):
                # só um pulso do corpo foi visto: ele fica com a mão mais perto dele
                lado = next(iter(conhecidos))
                escolha = {lado: 0 if custo(0, lado) <= custo(1, lado) else 1}
            else:
                escolha = {"lh": 0, "rh": 1} if jeito_a <= jeito_b else {"lh": 1, "rh": 0}
        elif custo(0, "lh") <= custo(0, "rh"):
            escolha = {"lh": 0}
        else:
            escolha = {"rh": 0}
        # Ignora mãos longe demais do pulso (provavelmente de outra pessoa ou um erro)
        return {lado: n for lado, n in escolha.items()
                if lado in conhecidos and distancia(pulsos_das_maos[n], conhecidos[lado]) <= DISTANCIA_MAXIMA}

    escolha = {}
    for n, rotulos in enumerate(maos.handedness):
        lado = "lh" if rotulos and rotulos[0].category_name == "Right" else "rh"
        escolha.setdefault(lado, n)
    return escolha


# =============================================================================
# FILTRO + MENSAGEM
# =============================================================================

class RastreadorMaos:
    """
    Guarda as duas mãos entre os quadros e as coloca na mensagem do Unity.
    O MediaPipe não dá confiança por dedo, então a mão inteira é boa ou não:
    se ela some por poucos quadros (tolerancia), os dedos ficam parados em vez de piscar.
    """

    def __init__(self, tolerancia=5, suavizar=False, min_cutoff=1.0, beta=0.05, conf_min=0.5):
        def novo(dims):
            return FiltroPontos(N_PONTOS_MAO, dims, conf_min=conf_min, tolerancia=tolerancia,
                                suavizar=suavizar, min_cutoff=min_cutoff, beta=beta)
        self.filtro_imagem = {lado: novo(2) for lado in ("lh", "rh")}   # "lhi", "rhi"
        self.filtro_mundo = {lado: novo(3) for lado in ("lh", "rh")}    # "lh", "rh"

    def preencher(self, msg, maos, pulsos, t):
        """maos: resultado do HandLandmarker (ou None); pulsos: veja qual_mao_e_qual; t: segundos."""
        escolha = qual_mao_e_qual(maos, pulsos)
        for lado in ("lh", "rh"):
            imagem = mundo = None
            n = escolha.get(lado)
            if n is not None:
                imagem = [(p.x, p.y) for p in maos.hand_landmarks[n]]
                if maos.hand_world_landmarks:
                    pontos = maos.hand_world_landmarks[n]
                    pulso = pontos[0]   # posições contadas a partir do pulso da mão
                    mundo = [(p.x - pulso.x, p.y - pulso.y, p.z - pulso.z) for p in pontos]

            pontos_imagem, _, validos_imagem = self.filtro_imagem[lado].atualizar(imagem, None, t)
            pontos_mundo, _, validos_mundo = self.filtro_mundo[lado].atualizar(mundo, None, t)
            preencher_mao(msg, lado,
                          pontos_imagem if validos_imagem.all() else None,
                          pontos_mundo if validos_mundo.all() else None)


# =============================================================================
# DESENHO
# =============================================================================

LIGACOES_MAO = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]
AZUL, ROSA = (255, 200, 0), (255, 0, 200)   # cores das mãos (o OpenCV usa a ordem BGR)


def desenhar_maos(imagem, msg):
    """Dedos em azul (mão do pulso 15) e rosa (mão do pulso 16), a partir da mensagem."""
    altura, largura = imagem.shape[:2]
    for campo, cor in (("lhi", AZUL), ("rhi", ROSA)):
        valores = msg[campo]
        if valores:
            pontos = [(int(valores[i * 2] * largura), int(valores[i * 2 + 1] * altura))
                      for i in range(N_PONTOS_MAO)]
            for a, b in LIGACOES_MAO:
                cv2.line(imagem, pontos[a], pontos[b], cor, 2, cv2.LINE_AA)
