@echo off
REM Génère BanqueGestion.exe (à lancer sur un PC Windows avec Python 3.10+ installé)
python -m pip install --upgrade pip pyinstaller pillow
python -m PyInstaller --noconfirm --onefile --windowed --name BanqueGestion banque.py
echo.
echo Termine. Votre programme est dans le dossier "dist" : dist\BanqueGestion.exe
echo La base de donnees (banque.db) et les photos seront creees a cote du .exe.
pause
