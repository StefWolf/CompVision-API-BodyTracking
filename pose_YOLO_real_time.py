"""
YOLO26-pose -> Unity (por UDP)
==============================

O que este programa faz, a cada imagem da webcam:
  1. Lê a imagem da câmera (e clareia, se o ambiente estiver escuro).
  2. Pede ao YOLO26-pose os 17 pontos do corpo da pessoa principal e, ao mesmo tempo,
     ao MediaPipe os 21 pontos de cada mão (se USAR_MAOS = True).
  3. Filtra os pontos pela confiança (segura pontos perdidos por alguns quadros).
  4. Converte para o mesmo formato do MediaPipe e envia para o Unity (veja envio_unity.py).
  5. Mostra uma janela com o esqueleto e os dedos desenhados.

Como rodar (com o .venv ativo, dentro da pasta python):
    python pose_YOLO_real_time.py
Para fechar, aperte Q ou ESC com a janela selecionada.
"""

import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')   # evita o erro de memória do OpenBLAS no Windows

import time
import warnings
from concurrent.futures import ThreadPoolExecutor
warnings.filterwarnings('ignore', message='.*torch.jit.script.*')   # aviso inofensivo do Python 3.14

import cv2                                # o OpenCV, que lê o vídeo e mostra a janela
import mediapipe as mp                    # só para as mãos
import numpy as np                        # contas com os pontos
import torch                              # só para saber se a placa de vídeo está disponível
from ultralytics import YOLO              # os modelos YOLO do Ultralytics

from rastreamento.envio_unity import ConversorCOCO, EnviadorUnity, nova_mensagem   # formato e envio (igual ao MediaPipe)
from rastreamento.filtros_pose import FiltroPontos, pre_processar                  # filtros compartilhados com o MediaPipe
from rastreamento.maos_mediapipe import RastreadorMaos, criar_detector_maos, desenhar_maos   # mãos do MediaPipe
from rastreamento.pontos_pose import N_PONTOS_COCO, PontoCOCO


# =============================================================================
# CONFIGURAÇÕES (edite aqui)
# =============================================================================

CAMERA = 0                # 0 = webcam do notebook
ESPELHAR = False          # True = imagem como num espelho
MODELO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'yolo26n-pose.pt')  # o sufixo -pose é o modelo de pontos do corpo

# Mãos: o YOLO não tem dedos, então o MediaPipe Hand Landmarker roda junto (em paralelo)
USAR_MAOS = True          # True = detecta os dedos das duas mãos
CONFIANCA_MAOS = 0.5      # confiança mínima (0 a 1) para o MediaPipe considerar que achou uma mão

PRE_PROCESSAR = True      # True = clareia o quadro quando o ambiente estiver escuro
LIMITE_BRILHO = 90        # brilho médio (0 a 255) abaixo do qual o filtro é aplicado

CONF_MIN_KEYPOINT = 0.5   # confiança mínima (0 a 1) para um keypoint ser aceito
QUADROS_TOLERANCIA = 5    # por quantos quadros um ponto perdido repete o último valor bom

# Suavização (One Euro). O Unity JÁ suaviza (HumanoidAvatarDriver.cs): deixe False,
# senão o avatar fica com atraso. Ligue só para testar.
SUAVIZAR = False          # True = aplica o One Euro Filter nos keypoints
MIN_CUTOFF = 0.5          # menor = suaviza mais quando parado (mas cria mais atraso)
BETA = 0.05               # maior = reage mais rápido em movimentos rápidos (mas treme mais)

ENVIAR_PARA_UNITY = True  # False = só mostra a janela, sem enviar nada
DESCOBERTA_AUTOMATICA = True  # True = acha o Unity na rede sozinho (Editor neste PC ou o app no Meta Quest)
IP_DO_UNITY = '127.0.0.1' # usado só com DESCOBERTA_AUTOMATICA = False (127.0.0.1 = este mesmo computador)
PORTA_UDP = 5052          # a mesma configurada no PoseUdpReceiver do Unity


# =============================================================================
# 1. CARREGAR O MODELO (uma vez só, antes de começar)
# =============================================================================
# Carregar um modelo leva segundos. Então carregamos aqui, uma vez, e no laço lá embaixo só usamos.

print('Placa de vídeo:', torch.cuda.get_device_name(0) if torch.cuda.is_available()
      else 'NÃO encontrada (vai rodar no processador, mais lento)')

modelo = YOLO(MODELO)

# Mãos: o detector roda num "ajudante" (outra thread) ao mesmo tempo que o YOLO,
# assim o tempo das mãos não se soma ao do corpo.
detector_maos = criar_detector_maos(CONFIANCA_MAOS) if USAR_MAOS else None
ajudante = ThreadPoolExecutor(1) if detector_maos else None


def detectar_maos(imagem_mp, tempo_ms):
    """Roda o detector de mãos e devolve (resultado, milissegundos gastos)."""
    antes = time.time()
    resultado = detector_maos.detect_for_video(imagem_mp, tempo_ms)
    return resultado, (time.time() - antes) * 1000


def pulsos_do_corpo(pontos, conf, largura, altura):
    """
    Pulsos do YOLO (de 0 a 1 na imagem), para prender cada mão ao pulso certo.
    "lh" = pulso esquerdo (vira o ponto 15 no Unity), "rh" = direito (16). None = pulso não visto.
    """
    pulsos = {}
    for lado, ponto in (('lh', PontoCOCO.PULSO_ESQUERDO), ('rh', PontoCOCO.PULSO_DIREITO)):
        bom = conf[ponto] >= CONF_MIN_KEYPOINT and not np.isnan(pontos[ponto]).any()
        pulsos[lado] = (pontos[ponto][0] / largura, pontos[ponto][1] / altura) if bom else None
    return pulsos


def pessoa_principal(resultado):
    """Pega a pessoa com maior confiança. Devolve (xy (17,2) em pixels, conf (17,)) ou (None, None)."""
    kps = getattr(resultado, 'keypoints', None)
    if kps is None or len(kps) == 0:
        return None, None

    caixas = getattr(resultado, 'boxes', None)
    idx = int(caixas.conf.argmax()) if caixas is not None and len(caixas) else 0

    xy = kps.xy[idx].cpu().numpy()
    conf = kps.conf[idx].cpu().numpy() if kps.conf is not None else np.ones(len(xy))
    return xy, conf


def contar_pessoas(resultado):
    """Quantas pessoas o modelo encontrou (uma lista de pontos por pessoa)."""
    pontos = getattr(resultado, 'keypoints', None)
    return 0 if pontos is None else len(pontos)


def escrever(imagem, texto, y):
    """Escreve um texto amarelo sobre uma faixa preta, para ler bem em qualquer fundo."""
    fonte, tamanho, espessura = cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1
    (largura, altura), _ = cv2.getTextSize(texto, fonte, tamanho, espessura)
    cv2.rectangle(imagem, (5, y - altura - 6), (15 + largura, y + 6), (0, 0, 0), -1)   # faixa preta
    cv2.putText(imagem, texto, (10, y), fonte, tamanho, (0, 255, 255), espessura, cv2.LINE_AA)


# Guarda os 17 keypoints de UMA pessoa entre os quadros: filtra pela confiança,
# segura pontos perdidos por alguns quadros e (se SUAVIZAR) suaviza. Veja filtros_pose.py.
filtro_keypoints = FiltroPontos(N_PONTOS_COCO, 2, conf_min=CONF_MIN_KEYPOINT, tolerancia=QUADROS_TOLERANCIA,
                                suavizar=SUAVIZAR, min_cutoff=MIN_CUTOFF, beta=BETA)

# Converte os 17 pontos do YOLO para os 33 do formato do Unity (com pseudo-3D). Veja envio_unity.py.
conversor = ConversorCOCO(conf_min=CONF_MIN_KEYPOINT)

# Filtra as mãos entre os quadros e coloca na mensagem. Veja maos_mediapipe.py.
rastreador_maos = RastreadorMaos(tolerancia=QUADROS_TOLERANCIA, suavizar=SUAVIZAR,
                                 min_cutoff=MIN_CUTOFF, beta=BETA)


# =============================================================================
# 2. ABRIR A WEBCAM E A CONEXÃO COM O UNITY
# =============================================================================

# No Windows, o modo DirectShow (CAP_DSHOW) abre a webcam mais rápido
video = cv2.VideoCapture(CAMERA, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
if not video.isOpened():
    raise RuntimeError('Não consegui abrir a webcam')

envio = EnviadorUnity(IP_DO_UNITY, PORTA_UDP, descoberta=DESCOBERTA_AUTOMATICA) if ENVIAR_PARA_UNITY else None

print('Rodando!' + (f' Enviando para o Unity: {envio.descricao()}.' if envio else '')
      + ' Aperte Q ou ESC na janela para sair.')


# =============================================================================
# 3. LAÇO: repete para cada quadro da webcam
# =============================================================================

fps = 0.0
numero_frame = 0
ultimo_tempo_ms = -1
ms_maos = 0.0
try:
    while True:
        inicio = time.time()

        ok, quadro = video.read()             # lê o quadro mais novo
        if not ok:
            continue                          # às vezes a câmera falha um quadro: tenta o próximo
        if ESPELHAR:
            quadro = cv2.flip(quadro, 1)

        quadro, brilho, filtrou = pre_processar(quadro, PRE_PROCESSAR, LIMITE_BRILHO)   # clareia se estiver escuro

        # --- Mãos: começa a detecção no ajudante (o MediaPipe quer RGB e um tempo sempre crescente) ---
        tarefa_maos = None
        if ajudante:
            imagem_mp = mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
            tempo_ms = max(int(time.time() * 1000), ultimo_tempo_ms + 1)
            ultimo_tempo_ms = tempo_ms
            tarefa_maos = ajudante.submit(detectar_maos, imagem_mp, tempo_ms)

        # --- Corpo (o Ultralytics devolve uma lista, e o [0] pega o resultado da única imagem) ---
        antes = time.time()
        resultado = modelo(quadro, verbose=False)[0]
        ms = (time.time() - antes) * 1000

        maos = None
        if tarefa_maos:
            maos, ms_maos = tarefa_maos.result()   # espera as mãos terminarem (se ainda não terminaram)

        # --- Keypoints filtrados pela confiança (é isso que vai para o Unity) ---
        agora = time.time()
        xy, conf = pessoa_principal(resultado)
        pontos, conf, validos = filtro_keypoints.atualizar(xy, conf, agora)

        # --- Mensagem para o Unity (também usada para desenhar as mãos) ---
        altura, largura = quadro.shape[:2]
        msg = nova_mensagem(numero_frame, agora, largura, altura, fonte='yolo')
        conversor.preencher(msg, pontos, conf)   # sem pontos bons, vai com detected = False
        if detector_maos:
            rastreador_maos.preencher(msg, maos, pulsos_do_corpo(pontos, conf, largura, altura), agora)
        if envio:
            envio.enviar(msg)
        numero_frame += 1

        # --- Janela: esqueleto do YOLO + círculos verdes nos pontos aceitos pelo filtro + dedos ---
        tela = resultado.plot(img=quadro.copy())
        for x, y in pontos[validos]:
            cv2.circle(tela, (int(x), int(y)), 5, (0, 255, 0), -1)
        desenhar_maos(tela, msg)   # azul = mão do pulso esquerdo, rosa = do direito

        tempo_maos = f' | maos: {ms_maos:.0f} ms' if detector_maos else ''
        escrever(tela, f'YOLO26: {ms:.0f} ms{tempo_maos} | {contar_pessoas(resultado)} pessoa(s)', 25)
        escrever(tela, f'Brilho: {brilho:.0f} | Filtro: {"LIGADO" if filtrou else "desligado"}', 55)
        escrever(tela, f'Pontos validos: {validos.sum()}/{N_PONTOS_COCO} | '
                       f'Suavizar: {"LIGADO" if SUAVIZAR else "desligado"}', 85)
        escrever(tela, f'{fps:.1f} FPS', tela.shape[0] - 15)
        cv2.imshow('YOLO26 -> Unity (Q para sair)', tela)

        if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
            break

        fps_agora = 1 / max(time.time() - inicio, 1e-6)
        fps = fps_agora if fps == 0 else 0.9 * fps + 0.1 * fps_agora
finally:
    video.release()                           # libera a webcam
    if ajudante:
        ajudante.shutdown()
    if detector_maos:
        detector_maos.close()
    if envio:
        envio.fechar()
    cv2.destroyAllWindows()
