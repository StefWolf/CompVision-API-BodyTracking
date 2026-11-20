"""
Receptor UDP de teste: mostra no terminal o que o Unity vai receber.
Útil para verificar o envio sem abrir o Unity.

    python ferramentas/udp_test_receiver.py              # pose_MEDIAPIPE_real_time.py ou pose_YOLO_real_time.py, porta 5052

O campo "src" mostra de qual modelo veio a mensagem (mediapipe ou yolo).
No YOLO, calcanhares e pontas dos pés não existem e chegam como 0.
"""

import argparse
import json
import socket

FEET = {27: "tornozelo E", 28: "tornozelo D", 29: "calcanhar E",
        30: "calcanhar D", 31: "ponta pé E", 32: "ponta pé D"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5052)
    p.add_argument("--count", type=int, default=0, help="parar após N mensagens (0 = infinito)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    print(f"Escutando UDP na porta {args.port} (Ctrl+C para sair)...")

    n = 0
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            msg = json.loads(data.decode("utf-8"))
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
