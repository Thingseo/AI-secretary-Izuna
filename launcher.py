"""Keep first-launch failures visible when launched by pythonw.exe."""
import ctypes
import os
import sys
import traceback
from pathlib import Path

if __name__ == '__main__':
    try:
        from app import main
        sys.exit(main())
    except Exception:
        folder = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'IzunaDesktop'
        try:
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / 'startup-error.log'
            log.write_text(traceback.format_exc(), encoding='utf-8')
            message = f'이즈나를 시작하지 못했어요. 오류 기록:\n{log}\n\nZIP 전체를 압축 해제했는지 확인해 주세요.'
        except OSError:
            message = '이즈나를 시작하지 못했고 오류 기록도 저장하지 못했어요. 폴더의 쓰기 권한을 확인해 주세요.'
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None, message, 'Izuna Desktop', 0x10)
        else:
            traceback.print_exc()
        sys.exit(1)
