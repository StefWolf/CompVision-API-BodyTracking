"""
Receptor UDP de teste: mostra no terminal o que o Unity vai receber.
Útil para verificar o envio sem abrir o Unity.

    python ferramentas/udp_test_receiver.py              # pose_MEDIAPIPE_real_time.py ou pose_YOLO_real_time.py, porta 5052

Faz a mesma descoberta do Unity: a cada 1 s diz "estou aqui" ao PC (porta 5053), então funciona
com DESCOBERTA_AUTOMATICA = True. Pode rodar em outro computador da rede para testar o caminho do Quest.

O campo "src" mostra de qual modelo veio a mensagem (mediapipe ou yolo).
No YOLO, calcanhares e pontas dos pés não existem e chegam como 0.
"""

import argparse
import json
import socket
import time
import uuid

APP = "pose-tracking"     # mesma assinatura do rastreamento/envio_unity.py
PORTA_DO_PC = 5053        # onde o Python escuta o "estou aqui"

FEET = {27: "tornozelo E", 28: "tornozelo D", 29: "calcanhar E",
        30: "calcanhar D", 31: "ponta pé E", 32: "ponta pé D"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5052)
    p.add_argument("--count", type=int, default=0, help="parar após N mensagens (0 = infinito)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        # Windows: enviar para uma porta sem ninguém escutando faria o próximo recvfrom dar erro
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.2)
    print(f"Escutando UDP na porta {args.port} (Ctrl+C para sair)...")

    ola = json.dumps({"type": "hello", "app": APP, "port": args.port, "id": uuid.uuid4().hex,
                      "device": f"udp_test_receiver ({socket.gethostname()})"}).encode("utf-8")
    pc = None               # endereço do PC, quando o aviso dele chegar
    proximo_ola = 0.0

    n = 0
    try:
        while True:
            # "estou aqui" a cada 1 s: por broadcast, para este PC e direto para o PC, se já for conhecido
            if time.time() >= proximo_ola:
                proximo_ola = time.time() + 1.0
                for destino in [("255.255.255.255", PORTA_DO_PC), ("127.0.0.1", PORTA_DO_PC)] + ([pc] if pc else []):
                    try:
                        sock.sendto(ola, destino)
                    except OSError:
                        pass

            try:
                data, addr = sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            msg = json.loads(data.decode("utf-8"))

            if msg.get("type") == "pc_announce":
                if msg.get("app") == APP and pc is None:
                    pc = (addr[0], int(msg.get("port", PORTA_DO_PC)))
                    print(f"PC das poses encontrado em {pc[0]}")
                continue
            n += 1

            w = msg.get("wlm") or []
            if msg["detected"] and w:
                corpo_txt = " | ".join(
                    f"{name}: ({w[i*3]:+.2f},{w[i*3+1]:+.2f},{w[i*3+2]:+.2f})" for i, name in FEET.items())
            else:
                corpo_txt = "sem pessoa"

            maos = []
            for key, nome in (("lh", "mão 15"), ("rh", "mão 16")):
                hp = msg.get(key) or []
                if hp:
                    # ponta do indicador (ponto 8) relativa ao pulso da mão, em cm
                    maos.append(f"{nome} indicador: ({hp[24]*100:+.1f},{hp[25]*100:+.1f},{hp[26]*100:+.1f}) cm")
            maos_txt = " | ".join(maos) if maos else "sem mãos"

            fbs = msg.get("fbs") or []
            if len(fbs) >= 52:
                # índices: 9 eyeBlinkLeft, 10 eyeBlinkRight, 25 jawOpen, 44/45 mouthSmile
                rosto_txt = (f"boca {fbs[25]:.2f} | piscada E {fbs[9]:.2f} D {fbs[10]:.2f} | "
                             f"sorriso {(fbs[44] + fbs[45]) / 2:.2f}")
            else:
                rosto_txt = "sem rosto"

            print(f"[{msg.get('src', '?')}] frame {msg['frame']:>6} | {len(data)} bytes | "
                  f"{corpo_txt} | {maos_txt} | {rosto_txt}")
            if args.count and n >= args.count:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
