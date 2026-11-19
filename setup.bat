@echo off
REM Cria o ambiente virtual e instala as dependencias (rodar uma vez).
cd /d "%~dp0"
py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
REM torch com CUDA (GPU) primeiro; senao o ultralytics instala a versao so para CPU.
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
echo.
echo Pronto. Rode run_sender.bat para iniciar a deteccao.
pause
