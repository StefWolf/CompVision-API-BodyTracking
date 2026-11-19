"""
MediaPipe -> Unity (por UDP)
============================

O que este programa faz, a cada imagem da webcam:
  1. Lê a imagem da câmera (e clareia, se o ambiente estiver escuro).
  2. Pede ao MediaPipe para encontrar:
       - o CORPO  (33 pontos, incluindo os pés)       -> sempre
       - as MÃOS  (21 pontos em cada mão)             -> se USAR_MAOS = True
       - o ROSTO  (478 pontos + 52 expressões)        -> se USAR_ROSTO = True
  3. Filtra os pontos pela visibilidade (segura pontos perdidos por alguns quadros).
  4. Monta uma mensagem com tudo e envia para o Unity pela rede (UDP).
  5. Mostra uma janela com o esqueleto desenhado.

Como rodar (com o ambiente .venv ativo, dentro da pasta python):
    python pose_MEDIAPIPE_real_time.py

Para mudar o comportamento, edite as CONFIGURAÇÕES logo abaixo.
Para fechar, aperte Q ou ESC com a janela selecionada.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from envio_unity import EnviadorUnity, nova_mensagem, preencher_corpo
from filtros_pose import FiltroPontos, pre_processar
from maos_mediapipe import (SITE_MODELOS, RastreadorMaos, baixar_modelo as baixar_arquivo_modelo,
                            criar_detector_maos, desenhar_maos)


# =============================================================================
# CONFIGURAÇÕES (edite aqui)
# =============================================================================

# O que detectar além do corpo (o corpo é sempre detectado)
USAR_MAOS = True         # True = detecta os dedos das duas mãos
USAR_ROSTO = False        # True = detecta o rosto (expressões e rotação da cabeça)

# Rosto: enviar também os 478 pontos do rosto? (só vale se USAR_ROSTO = True)
#   True  = envia tudo (mensagem maior, ~10 KB por imagem)
#   False = envia só as 52 expressões e a rotação da cabeça (mensagem bem menor)
ENVIAR_PONTOS_DO_ROSTO = True

# Modelo do corpo: "lite" = mais rápido | "full" = equilibrado | "heavy" = mais preciso
MODELO_DO_CORPO = "lite"

# Rodar corpo, mãos e rosto ao mesmo tempo (mais rápido). False = um depois do outro.
RODAR_EM_PARALELO = True

# Confiança mínima (0 a 1) para o MediaPipe considerar que encontrou algo
CONFIANCA_MINIMA = 0.5

# Pouca luz: clareia o quadro (CLAHE) quando o brilho médio fica abaixo do limite
PRE_PROCESSAR = True      # True = liga o pré-processamento
LIMITE_BRILHO = 90        # brilho médio (0 a 255) abaixo do qual o filtro é aplicado

# Filtro dos pontos do corpo e das mãos
VISIBILIDADE_MINIMA = 0.5 # pontos do corpo abaixo disso são considerados ruins (e não são desenhados)
QUADROS_TOLERANCIA = 5    # por quantos quadros um ponto/mão perdido repete o último valor bom

# Suavização (One Euro). O Unity JÁ suaviza (HumanoidAvatarDriver.cs): deixe False,
# senão o avatar fica com atraso. Ligue só para testar.
SUAVIZAR = False
MIN_CUTOFF = 1.0          # menor = suaviza mais quando parado (mas cria mais atraso)
BETA = 0.05               # maior = reage mais rápido em movimentos rápidos (mas treme mais)

CAMERA = 0               # 0 = webcam do notebook; 1, 2... = outras câmeras
VIDEO = None             # caminho de um vídeo para testar no lugar da câmera (ex.: "teste.mp4")
LARGURA, ALTURA = 640, 480
ESPELHAR = True          # True = imagem como num espelho
MOSTRAR_JANELA = True    # False = não abre a janela

IP_DO_UNITY = "127.0.0.1"  # 127.0.0.1 = este mesmo computador
PORTA_UDP = 5052           # a mesma configurada no PoseUdpReceiver do Unity


# =============================================================================
# 1. MODELOS DO MEDIAPIPE
# =============================================================================

# O modelo das mãos fica no maos_mediapipe.py (é compartilhado com o YOLO)
ENDERECO_MODELO = {
    "corpo": f"{SITE_MODELOS}/pose_landmarker/pose_landmarker_{MODELO_DO_CORPO}/float16/latest/"
             f"pose_landmarker_{MODELO_DO_CORPO}.task",
    "rosto": f"{SITE_MODELOS}/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}


def baixar_modelo(qual):
    """Baixa o arquivo do modelo na primeira vez e devolve onde ele está salvo."""
    return baixar_arquivo_modelo(ENDERECO_MODELO[qual], qual)


def criar_detectores():
    """Cria os detectores do MediaPipe que estão ligados nas CONFIGURAÇÕES."""
    modo_video = vision.RunningMode.VIDEO   # modo para sequência de imagens (webcam)
    detectores = {}

    detectores["corpo"] = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=baixar_modelo("corpo")),
        running_mode=modo_video,
        num_poses=1,                                   # uma pessoa
        min_pose_detection_confidence=CONFIANCA_MINIMA,
        min_pose_presence_confidence=CONFIANCA_MINIMA,
        min_tracking_confidence=CONFIANCA_MINIMA))

    if USAR_MAOS:
        detectores["maos"] = criar_detector_maos(CONFIANCA_MINIMA)   # as duas mãos

    if USAR_ROSTO:
        detectores["rosto"] = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=baixar_modelo("rosto")),
            running_mode=modo_video,
            num_faces=1,                               # um rosto
            min_face_detection_confidence=CONFIANCA_MINIMA,
            min_face_presence_confidence=CONFIANCA_MINIMA,
            min_tracking_confidence=CONFIANCA_MINIMA,
            output_face_blendshapes=True,              # as 52 expressões (piscar, sorrir...)
            output_facial_transformation_matrixes=True))  # a rotação da cabeça

    return detectores


# =============================================================================
# 2. MENSAGEM PARA O UNITY
# =============================================================================
#
# O formato da mensagem (campos "lm", "wlm", "lh", "rh"...) é o mesmo do YOLO e está
# descrito no envio_unity.py. Aqui só tiramos os pontos do MediaPipe, filtramos e preenchemos.
# "fbs" segue a ordem de NOMES_DAS_EXPRESSOES.

NOMES_DAS_EXPRESSOES = [
    "_neutral", "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft",
    "browOuterUpRight", "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft",
    "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft",
    "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft",
    "jawOpen", "jawRight", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight", "mouthPucker", "mouthRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft",
    "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    "noseSneerLeft", "noseSneerRight",
]

PULSO_ESQUERDO, PULSO_DIREITO = 15, 16   # números dos pulsos no corpo do MediaPipe


# Filtros que guardam o estado dos pontos entre os quadros (veja filtros_pose.py).
#   Corpo: a visibilidade de cada ponto decide se ele é bom.
#   Mãos:  veja RastreadorMaos no maos_mediapipe.py.
def _novo_filtro(n_pontos, dims):
    return FiltroPontos(n_pontos, dims, conf_min=VISIBILIDADE_MINIMA, tolerancia=QUADROS_TOLERANCIA,
                        suavizar=SUAVIZAR, min_cutoff=MIN_CUTOFF, beta=BETA)

FILTRO_CORPO_IMAGEM = _novo_filtro(33, 3)                              # "lm"  (x, y, z na imagem)
FILTRO_CORPO_MUNDO = _novo_filtro(33, 3)                               # "wlm" (x, y, z em metros)
RASTREADOR_MAOS = RastreadorMaos(tolerancia=QUADROS_TOLERANCIA, suavizar=SUAVIZAR,
                                 min_cutoff=MIN_CUTOFF, beta=BETA, conf_min=VISIBILIDADE_MINIMA)


def montar_mensagem(numero_frame, largura, altura, corpo, maos, rosto):
    """Junta os resultados do MediaPipe numa mensagem (dicionário) para o Unity."""
    agora = time.time()
    msg = nova_mensagem(numero_frame, agora, largura, altura, fonte="mediapipe")

    # --- Corpo ---
    pontos_corpo = imagem = mundo = visibilidade = None
    if corpo is not None and corpo.pose_landmarks:
        pontos_corpo = corpo.pose_landmarks[0]
        imagem = [(p.x, p.y, p.z) for p in pontos_corpo]
        visibilidade = [p.visibility or 0.0 for p in pontos_corpo]
        if corpo.pose_world_landmarks:
            mundo = [(p.x, p.y, p.z) for p in corpo.pose_world_landmarks[0]]

    lm, conf, validos = FILTRO_CORPO_IMAGEM.atualizar(imagem, visibilidade, agora)
    wlm, _, _ = FILTRO_CORPO_MUNDO.atualizar(mundo, visibilidade, agora)
    if validos.any():   # corpo encontrado agora, ou perdido há poucos quadros
        preencher_corpo(msg, lm, conf, wlm)

    # --- Mãos ---
    pulsos = None
    if pontos_corpo is not None:   # pulsos do corpo, para prender cada mão ao pulso certo
        pulsos = {"lh": (pontos_corpo[PULSO_ESQUERDO].x, pontos_corpo[PULSO_ESQUERDO].y),
                  "rh": (pontos_corpo[PULSO_DIREITO].x, pontos_corpo[PULSO_DIREITO].y)}
    RASTREADOR_MAOS.preencher(msg, maos, pulsos, agora)

    # --- Rosto ---
    if rosto is not None and rosto.face_landmarks:
        if ENVIAR_PONTOS_DO_ROSTO:
            msg["fl"] = [round(v, 4) for p in rosto.face_landmarks[0] for v in (p.x, p.y, p.z)]
        if rosto.face_blendshapes:
            expressoes = sorted(rosto.face_blendshapes[0], key=lambda e: e.index)
            msg["fbs"] = [round(e.score, 3) for e in expressoes]
        if rosto.facial_transformation_matrixes:
            msg["fm"] = [round(float(v), 4) for v in rosto.facial_transformation_matrixes[0].flatten()]

    return msg


# =============================================================================
# 3. DESENHO NA JANELA
# =============================================================================

LIGACOES_CORPO = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
]
CONTORNOS_ROSTO = [(c.start, c.end) for c in vision.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS]
PONTOS_DOS_PES = {27, 28, 29, 30, 31, 32}

VERDE, LARANJA, BRANCO, CINZA = (0, 255, 0), (0, 165, 255), (255, 255, 255), (200, 200, 200)


def desenhar(imagem, msg, rosto):
    """Desenha rosto, corpo e mãos por cima da imagem da câmera."""
    altura, largura = imagem.shape[:2]

    def em_pixels(x, y):
        return int(x * largura), int(y * altura)

    # Rosto: contornos (olhos, sobrancelhas, boca, contorno do rosto)
    if rosto is not None and rosto.face_landmarks:
        pontos = [em_pixels(p.x, p.y) for p in rosto.face_landmarks[0]]
        for a, b in CONTORNOS_ROSTO:
            cv2.line(imagem, pontos[a], pontos[b], CINZA, 1, cv2.LINE_AA)

    # Corpo: só os pontos com boa visibilidade (pés em laranja)
    if msg["detected"]:
        lm = msg["lm"]
        pontos = [em_pixels(lm[i * 4], lm[i * 4 + 1]) for i in range(33)]
        visivel = [lm[i * 4 + 3] >= VISIBILIDADE_MINIMA for i in range(33)]
        for a, b in LIGACOES_CORPO:
            if visivel[a] and visivel[b]:
                cv2.line(imagem, pontos[a], pontos[b], BRANCO, 2, cv2.LINE_AA)
        for i, p in enumerate(pontos):
            if visivel[i]:
                cv2.circle(imagem, p, 5 if i in PONTOS_DOS_PES else 4,
                           LARANJA if i in PONTOS_DOS_PES else VERDE, -1, cv2.LINE_AA)

    # Mãos: dedos em azul (mão do pulso 15) e rosa (mão do pulso 16)
    desenhar_maos(imagem, msg)


def escrever(imagem, texto, y):
    """Escreve um texto amarelo com contorno preto na imagem."""
    cv2.putText(imagem, texto, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(imagem, texto, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)


# =============================================================================
# 4. PROGRAMA PRINCIPAL
# =============================================================================

def detectar_medindo_tempo(detector, imagem, tempo_ms):
    """Roda um detector e devolve (resultado, milissegundos gastos)."""
    antes = time.time()
    resultado = detector.detect_for_video(imagem, tempo_ms)
    return resultado, (time.time() - antes) * 1000


def abrir_camera():
    if VIDEO:
        camera = cv2.VideoCapture(VIDEO)
    else:
        # No Windows, o modo DirectShow (CAP_DSHOW) abre a webcam mais rápido
        camera = cv2.VideoCapture(CAMERA, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    if not camera.isOpened():
        raise SystemExit(f"Não consegui abrir {VIDEO or f'a câmera {CAMERA}'}.")
    return camera


def main():
    detectores = criar_detectores()
    camera = abrir_camera()
    envio = EnviadorUnity(IP_DO_UNITY, PORTA_UDP)

    # "Ajudantes" que rodam corpo, mãos e rosto ao mesmo tempo, um em cada núcleo do processador
    ajudantes = ThreadPoolExecutor(len(detectores)) if RODAR_EM_PARALELO and len(detectores) > 1 else None

    print(f"Detectando: {', '.join(detectores)}. "
          f"Enviando para o Unity em {IP_DO_UNITY}:{PORTA_UDP}. Aperte Q ou ESC na janela para sair.")

    numero_frame, ultimo_tempo_ms = 0, -1
    ms_medio = {nome: 0.0 for nome in detectores}
    fps, inicio_segundo, frames_no_segundo = 0.0, time.time(), 0

    try:
        while True:
            # --- 1. Imagem da câmera ---
            ok, imagem = camera.read()
            if not ok:
                if VIDEO:
                    break      # o vídeo acabou
                continue
            if ESPELHAR:
                imagem = cv2.flip(imagem, 1)

            # Clareia se estiver escuro (só quando o brilho está abaixo do LIMITE_BRILHO)
            imagem, brilho, filtrou = pre_processar(imagem, PRE_PROCESSAR, LIMITE_BRILHO)

            # O MediaPipe quer a imagem em RGB (o OpenCV entrega em BGR) e um tempo sempre crescente
            imagem_mp = mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
            tempo_ms = max(int(time.time() * 1000), ultimo_tempo_ms + 1)
            ultimo_tempo_ms = tempo_ms

            # --- 2. Detecção (todos juntos, ou um depois do outro) ---
            if ajudantes:
                tarefas = {nome: ajudantes.submit(detectar_medindo_tempo, d, imagem_mp, tempo_ms)
                           for nome, d in detectores.items()}
                resultados = {nome: tarefa.result() for nome, tarefa in tarefas.items()}
            else:
                resultados = {nome: detectar_medindo_tempo(d, imagem_mp, tempo_ms)
                              for nome, d in detectores.items()}

            for nome, (_, ms) in resultados.items():
                ms_medio[nome] = ms if numero_frame == 0 else 0.9 * ms_medio[nome] + 0.1 * ms

            corpo = resultados["corpo"][0]
            maos = resultados["maos"][0] if "maos" in resultados else None
            rosto = resultados["rosto"][0] if "rosto" in resultados else None

            # --- 3. Enviar para o Unity ---
            altura, largura = imagem.shape[:2]
            msg = montar_mensagem(numero_frame, largura, altura, corpo, maos, rosto)
            envio.enviar(msg)
            numero_frame += 1

            # Conta quantos frames por segundo (FPS) estão saindo
            frames_no_segundo += 1
            if time.time() - inicio_segundo >= 1:
                fps = frames_no_segundo / (time.time() - inicio_segundo)
                inicio_segundo, frames_no_segundo = time.time(), 0
            tempos = " | ".join(f"{nome} {ms:.0f}ms" for nome, ms in ms_medio.items())

            # --- 4. Janela ---
            if MOSTRAR_JANELA:
                desenhar(imagem, msg, rosto)
                encontrou = [nome for nome, achou in (("corpo", msg["detected"]),
                                                      ("mao E", msg["lh"]), ("mao D", msg["rh"]),
                                                      ("rosto", msg["fbs"])) if achou]
                escrever(imagem, f"{fps:4.1f} FPS | encontrou: {', '.join(encontrou) or 'nada'}", 22)
                escrever(imagem, tempos, 44)
                escrever(imagem, f"Brilho: {brilho:.0f} | Filtro: {'LIGADO' if filtrou else 'desligado'}", 66)
                cv2.imshow("MediaPipe -> Unity (Q para sair)", imagem)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            elif frames_no_segundo == 0:
                print(f"{fps:4.1f} FPS | {tempos}")
    finally:
        if ajudantes:
            ajudantes.shutdown()
        for detector in detectores.values():
            detector.close()
        camera.release()
        envio.fechar()
        if MOSTRAR_JANELA:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
