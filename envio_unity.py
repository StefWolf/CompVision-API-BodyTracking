"""
Envio dos dados de pose para o Unity (UDP + JSON)
=================================================

Usado tanto pelo pose_YOLO_real_time.py quanto pelo pose_MEDIAPIPE_real_time.py,
para que os dois mandem EXATAMENTE o mesmo formato de mensagem.

Formato (os nomes curtos são os que o PoseUdpReceiver.cs do Unity espera).
Listas "achatadas" de números; lista vazia = não encontrou.

  "src"  : de qual modelo veio ("mediapipe" ou "yolo"); o Unity ignora este campo
  "frame", "t" : número do quadro e horário do envio
  "detected"   : True se há uma pessoa
  "w", "h"     : tamanho da imagem em pixels
  "lm"  : corpo, 33 pontos x (x, y, z, visibilidade), x e y de 0 a 1 na imagem
  "wlm" : corpo, 33 pontos x (x, y, z) em METROS, com o centro no quadril
  "lh"  : mão presa ao pulso 15 do corpo, 21 pontos x (x, y, z) em metros a partir do pulso
  "rh"  : mão presa ao pulso 16 do corpo (mesmo formato)
  "lhi", "rhi" : as mesmas mãos em posição na imagem, 21 pontos x (x, y)
  "fl"  : rosto, 478 pontos x (x, y, z) na imagem
  "fbs" : rosto, 52 expressões de 0 a 1
  "fm"  : rosto, matriz 4x4 com a rotação da cabeça

O YOLO só tem 17 pontos em 2D. Eles são colocados nas posições equivalentes dos 33
(pontos_pose.COCO_PARA_MEDIAPIPE) e o "wlm" é um PSEUDO-3D: as posições na imagem
convertidas para metros. A profundidade (z) de cotovelos, pulsos, joelhos e tornozelos é
estimada pelo encurtamento dos ossos na imagem; o resto fica com z = 0. Veja ConversorCOCO.
"""

import json
import socket

import numpy as np

from pontos_pose import COCO_PARA_MEDIAPIPE, N_PONTOS_MEDIAPIPE, PontoCOCO


# =============================================================================
# MONTAGEM DA MENSAGEM
# =============================================================================

def nova_mensagem(numero_frame, tempo, largura, altura, fonte):
    """Mensagem vazia (ninguém encontrado), pronta para ser preenchida."""
    return {"src": fonte, "frame": numero_frame, "t": round(tempo, 3), "detected": False,
            "w": largura, "h": altura,
            "lm": [], "wlm": [], "lh": [], "rh": [], "lhi": [], "rhi": [],
            "fl": [], "fbs": [], "fm": []}


def achatar(pontos, conf=None, casas=5):
    """Array (N, dims) -> lista plana de números (com a confiança no fim de cada ponto, se houver)."""
    pontos = np.nan_to_num(np.asarray(pontos, dtype=float))   # o JSON não aceita NaN: vira 0
    if conf is not None:
        pontos = np.column_stack((pontos, np.nan_to_num(np.asarray(conf, dtype=float))))
    return [round(float(v), casas) for v in pontos.ravel()]


def preencher_corpo(msg, imagem, visibilidade, mundo):
    """
    Coloca o corpo na mensagem.
      imagem       : (33, 3) x, y de 0 a 1 na imagem, e z
      visibilidade : (33,) de 0 a 1
      mundo        : (33, 3) em metros, centro no quadril (ou None)
    """
    msg["detected"] = True
    msg["lm"] = achatar(imagem, visibilidade)
    msg["wlm"] = achatar(mundo) if mundo is not None else []


def preencher_mao(msg, lado, imagem=None, mundo=None):
    """
    Coloca uma mão na mensagem. lado = "lh" (pulso 15) ou "rh" (pulso 16).
      imagem : (21, 2) x, y de 0 a 1 na imagem
      mundo  : (21, 3) em metros, a partir do pulso da mão
    """
    if imagem is not None:
        msg[lado + "i"] = achatar(imagem)
    if mundo is not None:
        msg[lado] = achatar(mundo)


# =============================================================================
# YOLO (COCO, 17 pontos 2D) -> FORMATO DO MEDIAPIPE (33 pontos + pseudo-3D)
# =============================================================================

class ConversorCOCO:
    """
    Converte os 17 pontos do YOLO para o formato do corpo da mensagem.

    O "wlm" (metros) é estimado a partir da imagem:
      - escala (pixels por metro): pela largura dos ombros e pela altura do tronco da pessoa,
        comparadas com medidas médias de um adulto. Usa a MAIOR das duas, porque girar o
        corpo só encolhe as medidas na imagem (nunca aumenta).
      - centro: o meio dos quadris (igual ao MediaPipe). Sem quadris na imagem (sentado na
        frente da webcam), estima o quadril abaixo dos ombros.
      - z: o YOLO não tem profundidade. Com estimar_profundidade=True, ela é deduzida pelo
        encurtamento dos ossos dos braços e das pernas: um osso que aparece mais curto do que
        o seu comprimento real está apontando para a câmera. Sem isso (z = 0), o avatar não
        acompanha o braço esticado para frente.
    """
    LARGURA_OMBROS_M = 0.36   # distância média entre os ombros de um adulto
    ALTURA_TRONCO_M = 0.50    # distância média do meio dos ombros ao meio dos quadris

    # Ossos dos membros, na ordem da cadeia (o z do fim soma ao z do início), com o
    # comprimento médio de um adulto em metros. Índices dos 33 pontos do MediaPipe.
    OSSOS = (
        (11, 13, 0.30), (13, 15, 0.26),   # braço esquerdo: ombro -> cotovelo -> pulso
        (12, 14, 0.30), (14, 16, 0.26),   # braço direito
        (23, 25, 0.42), (25, 27, 0.42),   # perna esquerda: quadril -> joelho -> tornozelo
        (24, 26, 0.42), (26, 28, 0.42),   # perna direita
    )
    ESQUECIMENTO_OSSO = 0.998   # por quadro: o maior comprimento visto "esquece" devagar (~6%/s a 30 fps)
    FOLGA_PROFUNDIDADE = 0.95   # osso com 95% ou mais do comprimento real = paralelo à imagem (z = 0)

    def __init__(self, conf_min=0.5, suavidade_escala=0.2, estimar_profundidade=True):
        self.conf_min = conf_min
        self.suavidade_escala = suavidade_escala   # 0 a 1: menor = escala muda mais devagar
        self.escala = None                         # pixels por metro (última estimativa)
        self.estimar_profundidade = estimar_profundidade
        # comprimento real de cada osso (m): o maior já visto, começando pela média de um adulto
        self.comprimentos = [padrao for _, _, padrao in self.OSSOS]

    def preencher(self, msg, xy, conf):
        """
        xy   : (17, 2) em pixels (pode ter NaN em pontos sem valor)
        conf : (17,) de 0 a 1
        Devolve True se colocou o corpo na mensagem.
        """
        xy = np.asarray(xy, dtype=float)
        conf = np.nan_to_num(np.asarray(conf, dtype=float))
        bom = (conf >= self.conf_min) & ~np.isnan(xy).any(axis=1)
        if not bom.any():
            return False

        largura, altura = msg["w"], msg["h"]
        self._atualizar_escala(xy, bom)
        centro = self._centro_do_quadril(xy, bom)

        imagem = np.zeros((N_PONTOS_MEDIAPIPE, 3))
        mundo = np.zeros((N_PONTOS_MEDIAPIPE, 3))
        visibilidade = np.zeros(N_PONTOS_MEDIAPIPE)
        for coco, mp in COCO_PARA_MEDIAPIPE.items():
            if np.isnan(xy[coco]).any():
                continue
            imagem[mp, :2] = xy[coco] / (largura, altura)
            mundo[mp, :2] = (xy[coco] - centro) / self.escala
            visibilidade[mp] = conf[coco]

        if self.estimar_profundidade:
            self._estimar_profundidade(mundo, visibilidade)

        preencher_corpo(msg, imagem, visibilidade, mundo)
        return True

    # ------------------------------------------------------------------

    @staticmethod
    def _meio(xy, bom, a, b):
        """Meio entre os pontos a e b, se os dois forem bons."""
        return (xy[a] + xy[b]) / 2 if bom[a] and bom[b] else None

    def _atualizar_escala(self, xy, bom):
        ombros = self._meio(xy, bom, PontoCOCO.OMBRO_ESQUERDO, PontoCOCO.OMBRO_DIREITO)
        quadris = self._meio(xy, bom, PontoCOCO.QUADRIL_ESQUERDO, PontoCOCO.QUADRIL_DIREITO)

        estimativas = []
        if ombros is not None:
            dist = np.linalg.norm(xy[PontoCOCO.OMBRO_ESQUERDO] - xy[PontoCOCO.OMBRO_DIREITO])
            estimativas.append(dist / self.LARGURA_OMBROS_M)
        if ombros is not None and quadris is not None:
            estimativas.append(np.linalg.norm(ombros - quadris) / self.ALTURA_TRONCO_M)

        nova = max(estimativas) if estimativas else None
        if nova is not None and nova > 1:
            # muda aos poucos, para o corpo inteiro não "pulsar" de tamanho a cada quadro
            self.escala = nova if self.escala is None else \
                (1 - self.suavidade_escala) * self.escala + self.suavidade_escala * nova
        if self.escala is None:
            self.escala = 500.0   # sem ombros ainda: um chute razoável para a webcam a ~1,5 m

    def _estimar_profundidade(self, mundo, visibilidade):
        """
        Preenche o z (metros) das juntas dos membros pelo encurtamento dos ossos na imagem.

        Comprimento real L, comprimento na imagem l: o osso aponta para a câmera com
        profundidade sqrt(L² - l²). O sinal é ambíguo (para frente ou para trás); assume
        PARA A CÂMERA, que é o caso comum (esticar o braço, sentar com as coxas para frente).
        Como no MediaPipe, z menor = mais perto da câmera.

        L é o maior comprimento visto recentemente (quando o osso estava paralelo à imagem),
        então se adapta a pessoas maiores ou menores que a média.
        """
        for n, (inicio, fim, padrao) in enumerate(self.OSSOS):
            if visibilidade[inicio] < self.conf_min or visibilidade[fim] < self.conf_min:
                continue
            l = float(np.linalg.norm(mundo[fim, :2] - mundo[inicio, :2]))

            # Aprende o comprimento real; ignora medidas absurdas (ponto trocado pelo detector)
            if l <= 1.4 * padrao:
                self.comprimentos[n] = max(l, self.comprimentos[n] * self.ESQUECIMENTO_OSSO, 0.7 * padrao)
            L = self.comprimentos[n]

            profundidade = 0.0
            if l < self.FOLGA_PROFUNDIDADE * L:
                profundidade = np.sqrt(L * L - l * l)
            mundo[fim, 2] = mundo[inicio, 2] - profundidade

    def _centro_do_quadril(self, xy, bom):
        quadris = self._meio(xy, bom, PontoCOCO.QUADRIL_ESQUERDO, PontoCOCO.QUADRIL_DIREITO)
        if quadris is not None:
            return quadris
        ombros = self._meio(xy, bom, PontoCOCO.OMBRO_ESQUERDO, PontoCOCO.OMBRO_DIREITO)
        if ombros is not None:   # quadril fora da imagem: fica um tronco abaixo dos ombros
            return ombros + (0.0, self.ALTURA_TRONCO_M * self.escala)
        return xy[bom].mean(axis=0)


# =============================================================================
# ENVIO UDP
# =============================================================================

class EnviadorUnity:
    """Envia as mensagens para o Unity por UDP. Use com 'with' ou chame fechar() no fim."""
    LIMITE_UDP = 65507        # maior pacote UDP possível
    LIMITE_SEGURO = 8192      # acima disso, fora deste computador, pacotes se perdem com mais frequência

    def __init__(self, ip="127.0.0.1", porta=5052):
        self.destino = (ip, porta)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ja_avisou = False

    def enviar(self, msg):
        """Envia a mensagem. Devolve quantos bytes foram enviados (0 se não enviou)."""
        dados = json.dumps(msg, separators=(",", ":"), allow_nan=False).encode("utf-8")

        if len(dados) > self.LIMITE_UDP:
            print(f"[envio] Mensagem de {len(dados)} bytes é grande demais para UDP: não enviada. "
                  f"Desligue ENVIAR_PONTOS_DO_ROSTO.")
            return 0
        if len(dados) > self.LIMITE_SEGURO and self.destino[0] not in ("127.0.0.1", "localhost") \
                and not self._ja_avisou:
            print(f"[envio] Aviso: mensagens de {len(dados)} bytes podem se perder na rede. "
                  f"Considere desligar ENVIAR_PONTOS_DO_ROSTO.")
            self._ja_avisou = True

        try:
            self.socket.sendto(dados, self.destino)
        except OSError as erro:   # rede fora do ar, por exemplo: não derruba o programa
            print(f"[envio] Falha ao enviar: {erro}")
            return 0
        return len(dados)

    def fechar(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
