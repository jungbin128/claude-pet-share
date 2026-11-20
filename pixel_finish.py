"""Optional palette treatments for the native pixel renderer; preserves every alpha pixel."""
from collections import deque
from PIL import Image, ImageFilter

FIRE_RAMP=((190,46,10),(216,61,11),(237,80,12),(250,106,16),
           (255,138,24),(255,170,42),(255,199,68),(255,221,102),(255,238,145))


def _outside_distance(img):
    w,h=img.size
    a=img.getchannel('A').load()
    outside=set();todo=deque()
    for x in range(w):
        for y in (0,h-1):
            if not a[x,y] and (x,y) not in outside:outside.add((x,y));todo.append((x,y))
    for y in range(h):
        for x in (0,w-1):
            if not a[x,y] and (x,y) not in outside:outside.add((x,y));todo.append((x,y))
    around=((1,0),(-1,0),(0,1),(0,-1))
    while todo:
        x,y=todo.popleft()
        for dx,dy in around:
            p=(x+dx,y+dy)
            if 0<=p[0]<w and 0<=p[1]<h and not a[p] and p not in outside:
                outside.add(p);todo.append(p)
    distance={};todo=deque()
    for y in range(h):
        for x in range(w):
            if a[x,y] and any((x+dx,y+dy) in outside for dx,dy in around):
                distance[x,y]=0;todo.append((x,y))
    while todo:
        x,y=todo.popleft()
        for dx,dy in around:
            p=(x+dx,y+dy)
            if 0<=p[0]<w and 0<=p[1]<h and a[p] and p not in distance:
                distance[p]=distance[x,y]+1;todo.append(p)
    return distance


def thin_outline(img):
    """Keep the outer dark contour; replace its thick inner band with local shading."""
    result=img.copy();src=img.load();dst=result.load();distance=_outside_distance(img)
    for (x,y),depth in distance.items():
        r,g,b,a=src[x,y]
        if not (1<=depth<=2 and r<145 and g<85 and b<70 and r>g*1.25):continue
        candidates=[]
        for dy in range(-3,4):
            for dx in range(-3,4):
                p=(x+dx,y+dy)
                if p not in distance or distance[p]<=depth:continue
                rr,gg,bb,aa=src[p]
                if aa and rr>155 and 65<gg<205 and bb<160 and rr>gg*1.2:
                    candidates.append((dx*dx+dy*dy,(rr,gg,bb)))
        if not candidates:continue
        nearest=min(t[0] for t in candidates)
        colors=[c for d,c in candidates if d==nearest]
        inner=tuple(round(sum(c[k] for c in colors)/len(colors)) for k in range(3))
        dst[x,y]=tuple(round(0.2*c+0.8*n) for c,n in zip((r,g,b),inner))+(a,)
    return result


def flame_gradient(img,light):
    """Diffuse only the flame's heat field, then quantize to nine crisp pixel colors."""
    w,h=img.size;lx,ly=light
    src=img.load();mask=Image.new('L',img.size);heat=Image.new('L',img.size)
    m,q=mask.load(),heat.load();points=[]
    for y in range(max(0,int(ly-16)),min(h,int(ly+7))):
        for x in range(max(0,int(lx-8)),min(w,int(lx+10))):
            r,g,b,a=src[x,y]
            # Protect the neighboring head/raised hand and the tail below the flame.
            if x<lx-5 and y>ly+1:continue
            if a and r>=160 and g>50 and r>b*1.4:
                m[x,y]=255;q[x,y]=round(max(0,min(1,(g-50)/170))*255);points.append((x,y))
    blurred=heat.filter(ImageFilter.GaussianBlur(0.95)).load()
    weights=mask.filter(ImageFilter.GaussianBlur(0.95)).load()
    out=img.copy();dst=out.load()
    for x,y in points:
        smooth=blurred[x,y]/max(1,weights[x,y])
        initial=q[x,y]/255
        t=max(0,min(1,0.2*initial+0.8*smooth))
        index=min(len(FIRE_RAMP)-1,int(t*(len(FIRE_RAMP)-1)+0.5))
        dst[x,y]=FIRE_RAMP[index]+(src[x,y][3],)
    return out



def flame_outline(img, light):
    """Give exposed flame pixels the body's one-pixel dark-brown contour."""
    lx, ly = light
    src = img.load()
    out = img.copy()
    dst = out.load()
    for (x, y), depth in _outside_distance(img).items():
        if depth or not (lx - 8 <= x < lx + 10 and ly - 16 <= y < ly + 7):
            continue
        if x < lx - 5 and y > ly + 1:
            continue
        r, g, b, a = src[x, y]
        if r >= 160 and g > 50 and r > b * 1.4:
            dst[x, y] = (100, 42, 18, a)
    return out



def clean_outline(img):
    """Unify the exposed warm contour while preserving alpha and facial/claw details."""
    src=img.load()
    out=img.copy()
    dst=out.load()
    for (x,y),depth in _outside_distance(img).items():
        if depth:
            continue
        r,g,b,a=src[x,y]
        # White claws/highlights and teal eye pixels remain unchanged.
        if r>g*1.15 and r>b*1.35:
            dst[x,y]=(112,53,27,a)
    return out


def apply(img,style,light=None):
    if not style:return img
    result=thin_outline(img) if style.get('outline')=='thin' else img
    if style.get('flame_gradient') and light is not None:
        result=flame_gradient(result,light)
    if style.get('flame_outline') and light is not None:
        result=flame_outline(result,light)
    if style.get('clean_outline'):
        result=clean_outline(result)
    return result
