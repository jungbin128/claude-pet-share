"""Persistent automatic-launch preference, independent of manual visibility."""
from pathlib import Path
import json
import os

MARKER = ".autostart-disabled"


def is_suspended(base):
    return (Path(base) / MARKER).exists()


def suspend(base):
    (Path(base) / MARKER).write_text("Automatic launch disabled; use the auto-launch toggle to enable.\n", encoding="utf8")


def set_enabled(base, enabled):
    if enabled:
        (Path(base) / MARKER).unlink(missing_ok=True)
    else:
        suspend(base)


def prepare_launch(base, automatic=False, source="login"):
    return not any((Path(base)/name).exists() for name in (".uninstalling",".update-in-progress")) and (not automatic or (not is_suspended(base) and get_mode(base)==source))


MODES={"login":"Windows 로그인 시", "claude":"Claude 실행 시"}


def get_mode(base):
    try:
        data=json.loads((Path(base)/'autorun.json').read_text(encoding='utf8'))
        return data['mode'] if isinstance(data,dict) and data.get('mode') in MODES else 'login'
    except (OSError,ValueError,KeyError):return 'login'


def set_mode(base, mode):
    if mode not in MODES:raise ValueError('Unknown automatic launch mode')
    path=Path(base)/'autorun.json';temporary=path.with_name(f'{path.name}.{os.getpid()}.tmp')
    try:
        temporary.write_text(json.dumps({'mode':mode})+'\n',encoding='utf8')
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def summary(base):
    return '꺼짐' if is_suspended(base) else ('로그인 시' if get_mode(base)=='login' else 'Claude')


def autorun_menu_items(base,back,toggle,select):
    enabled=not is_suspended(base);mode=get_mode(base)
    return [
        ('뒤로',back,False,True,{'icon':'back'}),None,
        ('자동 실행',toggle,False,True,{'icon':'clock','toggle':{'value':enabled,'label':'','change':toggle}}),
        ('실행 시점',None,False,True,{'section':True}),
        *[(label,lambda key=key:select(key),False,True,{'icon':'clock','selected':enabled and mode==key,'disabled':not enabled}) for key,label in MODES.items()],
    ]
