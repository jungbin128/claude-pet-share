"""Pixel-scale animated fire ribbons; rendered separately from character art."""
import math
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter

PHASES=64
FPS=8

def _ellipse(cx,cy,rx,ry,tilt,theta):
    x,y=rx*math.cos(theta),ry*math.sin(theta)
    return (cx+x*math.cos(tilt)-y*math.sin(tilt),cy+x*math.sin(tilt)+y*math.cos(tilt))

@lru_cache(maxsize=192)
def layers(width,height,ox,oy,sw,sh,phase,state,intensity=0.88):
    """Three broken moving ellipses, mostly behind the pet; no effects near its eyes."""
    phase=int(phase)%PHASES
    angle=phase*2*math.pi/PHASES
    back=Image.new('RGBA',(width,height))
    front=Image.new('RGBA',(width,height))
    cx=ox+sw*0.5
    strength=max(0.1,min(1,float(intensity)))
    if state=='done':strength=min(1,strength*1.15)
    # Coordinates relative to the actual sprite so different skins can opt in.
    specs=((cx,oy+sh*0.85,sw*0.54,sh*0.09,-0.10,1.0,0.0,4.1),
           (cx+sw*0.12,oy+sh*0.43,sw*0.46,sh*0.14,-0.95,-0.75,2.3,3.4),
           (cx-sw*0.06,oy+sh*0.09,sw*0.40,sh*0.075,-0.18,0.65,4.6,3.7))
    for ring,(xc,yc,rx,ry,tilt,speed,offset,length) in enumerate(specs):
        points=[]
        for j in range(50):
            u=j/49
            t=offset+angle*speed+u*length
            # Small fluctuations read as heat/flame, rather than perfect neon hoops.
            ripple=1+0.035*math.sin(t*7-angle*3+ring)
            x,y=_ellipse(xc,yc,rx*ripple,ry*(1+0.1*math.sin(t*5+angle*2)),tilt,t)
            x=max(2,min(width-3,int(round(x))));y=max(2,min(height-3,int(round(y))))
            points.append((x,y,u,t))
        for j in range(1,len(points)):
            x,y,u,t=points[j];px,py,_,_=points[j-1]
            taper=math.sin(math.pi*u)**0.55
            pulse=0.86+0.14*math.sin(t*3-angle*4)
            alpha=int(255*strength*taper*pulse)
            # The lower ribbon may pass in front at the feet, never over the face.
            target=front if ring==0 and y>=oy+sh*0.83 else back
            d=ImageDraw.Draw(target)
            d.line([(px,py),(x,y)],fill=(255,105,27,int(alpha*0.82)),width=3 if taper>0.5 else 1)
            d.line([(px,py),(x,y)],fill=(255,211,88,min(255,int(alpha*1.18))),width=2 if taper>0.65 else 1)
            if j%7==0 and taper>0.65:
                # Tiny curling flame tongue trailing the moving ribbon.
                tx=int(round(x+2*math.sin(t*2+angle)));ty=y-2
                d.line([(x,y),(tx,ty)],fill=(255,152,35,int(alpha*0.82)),width=1)
                d.point((x,y),fill=(255,238,160,min(255,int(alpha*1.15))))
    # Sparse low-opacity glow, composited once and cached for each phase.
    for target in (back,front):
        glow=target.filter(ImageFilter.GaussianBlur(1.25))
        glow.putalpha(glow.getchannel('A').point(lambda a:int(a*0.40)))
        glow.alpha_composite(target)
        target.paste(glow)
    return back,front
