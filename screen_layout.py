"""Screen-safe pet overlays. Rectangles are logical coordinates relative to the pet."""


def inside(rect, bounds):
    return rect[0]>=bounds[0] and rect[1]>=bounds[1] and rect[2]<=bounds[2] and rect[3]<=bounds[3]


def overlaps(a, b):
    return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]


def footprint(rect):
    x,y,r,b=rect
    return x-10,y-10,r+10,b+16  # shadow, close button and input handle


def clamp_rect(rect, bounds, pad=12):
    x,y,r,b=rect;w,h=r-x,b-y
    x=max(bounds[0]+pad,min(x,bounds[2]-pad-w))
    y=max(bounds[1]+pad,min(y,bounds[3]-pad-h))
    return x,y,x+w,y+h


def place_panel(bounds, pet, bar_y, size=(204,58)):
    w,h=size;l,t,r,b=pet
    candidates=[(-w/2,bar_y+8,w/2,bar_y+8+h),
                (l-w-14,bar_y-h,l-14,bar_y),
                (r+14,bar_y-h,r+14+w,bar_y),
                (-w/2,t-h-18,w/2,t-18)]
    for i,rect in enumerate(candidates):
        if i:
            rect=clamp_rect(rect,bounds)
        if inside((rect[0]-10,rect[1]-10,rect[2]+10,rect[3]+10),bounds) and not overlaps(rect,pet):
            return rect
    for rect in candidates[1:]:
        fitted=clamp_rect(rect,bounds)
        if not overlaps(fitted,pet):return fitted
    return clamp_rect(candidates[0],bounds)


def arrange_bubbles(entries, previous, bounds, obstacles):
    """Restore home positions first; retain safe fallbacks until home is available."""
    placed={};occupied=list(obstacles)
    def valid(rect):
        return inside(footprint(rect),bounds) and not any(overlaps(footprint(rect),r) for r in occupied)
    # Home positions win over temporary fallbacks. A little clearance avoids edge chatter.
    home_bounds=(bounds[0]+12,bounds[1]+12,bounds[2]-12,bounds[3]-12)
    for sid,w,h,preferred in entries:
        returning=previous.get(sid)!=preferred
        if valid(preferred) and (not returning or inside(footprint(preferred),home_bounds)):
            placed[sid]=preferred;occupied.append(footprint(preferred))
    # Keep valid fallbacks instead of repacking them on every pointer motion.
    for sid,w,h,preferred in entries:
        if sid in placed:continue
        if sid not in previous:continue
        x,y=previous[sid][:2];rect=(x,y,x+w,y+h)
        if valid(rect):placed[sid]=rect;occupied.append(footprint(rect))
    for sid,w,h,preferred in entries:
        if sid in placed:continue
        x,y=preferred[:2]
        search=(bounds[0]+28,bounds[1]+28,bounds[2]-28,bounds[3]-28)
        candidates=[clamp_rect(preferred,search,16)]
        xs={search[0]+12,search[2]-w-12,x}
        ys={search[1]+12,search[3]-h-18,y}
        for rect in obstacles+list(placed.values()):
            xs.update((rect[0]-w-22,rect[2]+22))
            ys.update((rect[1]-h-24,rect[3]+24))
        gx=search[0]+12
        while gx+w+12<=search[2]:xs.add(gx);gx+=w+24
        gy=search[1]+12
        while gy+h+18<=search[3]:ys.add(gy);gy+=h+28
        grid=[(a,c,a+w,c+h) for a in xs for c in ys]
        grid.sort(key=lambda r:(r[0]-x)**2+(r[1]-y)**2)
        candidates.extend(grid)
        result=next((r for r in candidates if valid(r) and inside(footprint(r),search)),None)
        if result is None:
            result=next((r for r in candidates if valid(r)),None)
        if result is None:
            # For physically crowded screens prefer visibility over clipping.
            result=clamp_rect(preferred,bounds,16)
            if grid:
                visible=[r for r in grid if inside(footprint(r),bounds)]
                if visible:
                    def cost(r):
                        overlap=0
                        f=footprint(r)
                        for q in occupied:
                            overlap+=max(0,min(f[2],q[2])-max(f[0],q[0]))*max(0,min(f[3],q[3])-max(f[1],q[1]))
                        return overlap,(r[0]-x)**2+(r[1]-y)**2
                    result=min(visible,key=cost)
        placed[sid]=result;occupied.append(footprint(result))
    return placed
