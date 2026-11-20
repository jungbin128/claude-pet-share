"""Per-conversation bubble preferences; absent overrides inherit global defaults."""
import math


def room_options(conf,sid):
    return conf.get('bubble_overrides',{}).get(sid,{}) if sid is not None else {}


def opacity_options(conf,sid=None):
    options=room_options(conf,sid)
    return (max(0,min(80,int(options.get('transparency',conf.get('bubble_transparency',30))))),
            bool(options.get('auto_transparency',conf.get('auto_transparency',True))))


def bubble_geometry(conf,sid,state,width=252):
    options=room_options(conf,sid)
    scale=max(.8,min(1.8,float(options.get('scale',1))))
    font=max(.8,min(1.6,float(options.get('font_scale',1))))
    row=max(scale,font*.85)
    return round(width*scale),math.ceil((84 if state=='working' else 54)*row),row,font,scale
