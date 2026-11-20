"""
Filtros compartilhados pelos scripts de pose (YOLO e MediaPipe)
===============================================================

  - pre_processar : clareia o quadro da webcam quando o ambiente está escuro (CLAHE)
  - FiltroOneEuro : suavização temporal de um ponto (tira a tremedeira)
  - FiltroPontos  : filtra N pontos pela confiança, segura pontos perdidos por alguns
                    quadros e (opcionalmente) suaviza com o One Euro

Sobre a suavização: o Unity (HumanoidAvatarDriver.cs) JÁ aplica o One Euro nos pontos.
Por isso, nos scripts, SUAVIZAR fica desligado por padrão: suavizar nos dois lados
só aumenta o atraso do avatar. Ligue apenas para testes.
"""

import cv2
import numpy as np


# =============================================================================
# PRÉ-PROCESSAMENTO (pouca luz)
# =============================================================================

# CLAHE: realça o contraste por regiões da imagem, sem estourar as partes claras.
# É criado uma vez só, para não recriar a cada quadro.
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def pre_processar(quadro, ativo=True, limite_brilho=90):
    """
    Clareia o quadro (BGR) só se ele estiver escuro.
    Devolve (quadro, brilho médio 0 a 255, aplicou o filtro?).
    """
    brilho = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY).mean()
    if not ativo or brilho >= limite_brilho:
        return quadro, brilho, False

    # aplica o CLAHE só no canal L (luminosidade) do espaço LAB, para não distorcer as cores
    l, a, b = cv2.split(cv2.cvtColor(quadro, cv2.COLOR_BGR2LAB))
    l = _clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR), brilho, True


# =============================================================================
# ONE EURO FILTER
# =============================================================================

class FiltroOneEuro:
    """
    One Euro Filter para um ponto (qualquer número de dimensões: x, y ou x, y, z).
    Parado, suaviza muito (tira a tremedeira); rápido, suaviza pouco (não atrasa o movimento).
      min_cutoff: menor = suaviza mais quando parado (mas cria mais atraso)
      beta:       maior = reage mais rápido em movimentos rápidos (mas treme mais)
    """
    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reiniciar()

    def reiniciar(self):
        self.x_ant = self.dx_ant = self.t_ant = None

    @staticmethod
    def _alfa(cutoff, dt):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x_ant is None:                # primeira medida: não há o que suavizar ainda
            self.x_ant, self.dx_ant, self.t_ant = x, np.zeros_like(x), t
            return x

        dt = max(t - self.t_ant, 1e-6)
        # 1) velocidade do ponto, também suavizada
        dx = (x - self.x_ant) / dt
        a_d = self._alfa(self.d_cutoff, dt)
        dx_suave = a_d * dx + (1 - a_d) * self.dx_ant
        # 2) quanto mais rápido, maior o cutoff, então menos suavização
        cutoff = self.min_cutoff + self.beta * np.linalg.norm(dx_suave)
        a = self._alfa(cutoff, dt)
        x_suave = a * x + (1 - a) * self.x_ant

        self.x_ant, self.dx_ant, self.t_ant = x_suave, dx_suave, t
        return x_suave


# =============================================================================
# FILTRO DE PONTOS (confiança + tolerância + suavização opcional)
# =============================================================================

class FiltroPontos:
    """
    Guarda o estado de N pontos entre os quadros.

    A cada quadro, para cada ponto:
      - confiança >= conf_min  -> ponto BOM: aceito (e suavizado, se suavizar=True)
      - confiança <  conf_min  -> repete o último valor bom por até `tolerancia` quadros
                                  (assim o ponto não "pisca" no Unity)
      - passou da tolerância   -> ponto PERDIDO

    atualizar() devolve (pontos, conf, validos):
      pontos  : array (N, dims). Válidos = valor bom/segurado. Perdidos = valor bruto do
                modelo (ou NaN se o modelo não mandou nada neste quadro).
      conf    : array (N,). Válidos = confiança do último valor bom. Perdidos = confiança bruta
                (baixa), para o Unity também saber que deve ignorar o ponto.
      validos : array (N,) de bool. True = ponto bom ou segurado.
    """

    def __init__(self, n_pontos, dims, conf_min=0.5, tolerancia=5,
                 suavizar=False, min_cutoff=1.0, beta=0.05):
        self.n, self.dims = n_pontos, dims
        self.conf_min, self.tolerancia, self.suavizar = conf_min, tolerancia, suavizar
        self.filtros = [FiltroOneEuro(min_cutoff, beta) for _ in range(n_pontos)]
        self.reiniciar()

    def reiniciar(self):
        """Esquece tudo (todos os pontos começam como perdidos)."""
        self.pontos = np.full((self.n, self.dims), np.nan)
        self.conf = np.zeros(self.n)
        self.perdidos = np.full(self.n, self.tolerancia + 1)   # há quantos quadros cada ponto está ruim
        for f in self.filtros:
            f.reiniciar()

    def atualizar(self, pontos, conf, t):
        """
        pontos: array (N, dims), ou None se o modelo não encontrou nada neste quadro.
        conf:   array (N,) de 0 a 1, ou None (= confiança 1 em todos).
        t:      tempo atual em segundos (usado só pela suavização).
        """
        if pontos is not None:
            pontos = np.asarray(pontos, dtype=float).reshape(self.n, self.dims)
            conf = np.ones(self.n) if conf is None else np.asarray(conf, dtype=float)

        for i in range(self.n):
            if pontos is not None and conf[i] >= self.conf_min:
                self.pontos[i] = self.filtros[i](pontos[i], t) if self.suavizar else pontos[i]
                self.conf[i] = conf[i]
                self.perdidos[i] = 0
            else:
                # ponto ruim: mantém o último valor bom por alguns quadros, depois descarta
                self.perdidos[i] = min(self.perdidos[i] + 1, self.tolerancia + 1)
                if self.perdidos[i] > self.tolerancia:
                    self.pontos[i] = np.nan
                    self.conf[i] = 0.0
                    self.filtros[i].reiniciar()   # ao reaparecer, começa do zero (sem "arrastar")

        validos = self.perdidos <= self.tolerancia
        saida_pontos, saida_conf = self.pontos.copy(), self.conf.copy()
        if pontos is not None:
            saida_pontos[~validos] = pontos[~validos]
            saida_conf[~validos] = conf[~validos]
        return saida_pontos, saida_conf, validos
