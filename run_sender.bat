@echo off
REM Inicia a captura da webcam e o envio UDP para o Unity.
REM
REM   run_sender.bat          -> MediaPipe (corpo 3D + maos + rosto)
REM   run_sender.bat yolo     -> YOLO26-pose (17 pontos, pseudo-3D)
REM
REM Para mudar o que e detectado, edite as CONFIGURACOES no topo do script escolhido.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
if /i "%~1"=="yolo" (
    python pose_YOLO_real_time.py
) else (
    python pose_MEDIAPIPE_real_time.py
)
pause
