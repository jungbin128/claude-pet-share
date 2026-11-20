"""Shared-state pet surfaces and monitor-relative synchronized positioning."""
from types import SimpleNamespace
import tkinter as tk
import time
import math


def corresponding_center(point, source, target):
    x, y = point
    l, t, r, b = source
    a, c, d, e = target
    return [round(a + (x-l) / max(1, r-l) * (d-a)),
            round(c + (y-t) / max(1, b-t) * (e-c))]


def edge_margins(margins):
    if len(margins)==2:return margins[0],margins[1],margins[0],margins[1]
    if len(margins)!=4:raise ValueError("Expected left/top/right/bottom margins")
    return tuple(margins)


def bounded_axis(value,start,end,before,after):
    lower,upper=math.ceil(start+before),math.floor(end-after)
    # If a huge pet cannot fit, keep its center on-screen without oscillating.
    if lower>upper:return round((start+end)/2)
    return min(upper,max(lower,round(value)))


def clamp_center(point,area,margins):
    left,top,right,bottom=edge_margins(margins)
    return [bounded_axis(point[0],area[0],area[2],left,right),
            bounded_axis(point[1],area[1],area[3],top,bottom)]


def shared_drag(point, dx, dy, source, anchor, areas, margins=(40, 60)):
    """Map motion while keeping the complete pet inside every monitor work area."""
    l,t,r,b=anchor;aw,ah=max(1,r-l),max(1,b-t)
    sw,sh=max(1,source[2]-source[0]),max(1,source[3]-source[1])
    fx=(point[0]-l)/aw+dx/sw;fy=(point[1]-t)/ah+dy/sh
    left,top,right,bottom=edge_margins(margins)
    areas=areas or [anchor]
    xmin=max(left/max(1,a[2]-a[0]) for a in areas)
    xmax=min(1-right/max(1,a[2]-a[0]) for a in areas)
    ymin=max(top/max(1,a[3]-a[1]) for a in areas)
    ymax=min(1-bottom/max(1,a[3]-a[1]) for a in areas)
    return [bounded_axis(l+fx*aw,l,r,xmin*aw,(1-xmax)*aw),
            bounded_axis(t+fy*ah,t,b,ymin*ah,(1-ymax)*ah)]


class MirroredPets:
    EVENTS = (("<ButtonPress-1>", "on_press"), ("<B1-Motion>", "on_drag"),
              ("<ButtonRelease-1>", "on_release"), ("<ButtonRelease-3>", "on_right"),
              ("<Motion>", "on_motion"), ("<Leave>", "on_leave"))

    def __init__(self, app, enumerate_areas, work_area, layered, scale):
        self.app, self.enumerate_areas, self.work_area = app, enumerate_areas, work_area
        self.layered, self.scale = layered, scale
        self.root_view = self.make_view(app.root, app.layer)
        self.mirrors = {}
        self.areas = []
        self.last_image = None
        self._image_bbox = None
        self._area_images = {}
        self._bbox_cache = {}
        self._next_scan = 0.0
        self.event_origin = None
        self.event_area = work_area(app.pc)
        self.menu_center = list(app.pc)

    def make_view(self, win, layer):
        view = SimpleNamespace(win=win, layer=layer, crop=(0, 0), origin=(0, 0),
                               center=list(self.app.pc), area=self.work_area(self.app.pc), rect=None)
        for sequence, name in self.EVENTS:
            win.bind(sequence, lambda event, v=view, n=name: self.dispatch(v, n, event))
        return view

    def dispatch(self, view, name, event):
        self.event_origin = view.origin
        self.event_area = view.area
        if name == "on_right":
            self.menu_center = list(view.center)
        translated = SimpleNamespace(**vars(event))
        translated.x += view.crop[0]
        translated.y += view.crop[1]
        getattr(self.app, name)(translated)
        if name == "on_motion" and view.win.winfo_exists():
            view.win.config(cursor=self.app.root.cget("cursor"))

    def sync(self):
        now = time.monotonic()
        if now >= self._next_scan or not self.areas:
            self.areas = self.enumerate_areas()
            self._next_scan = now + 2
        areas = self.areas
        anchor = self.work_area(self.app.pc)
        if self.app.conf.get("all_monitors",False):
            corrected=shared_drag(self.app.pc,0,0,anchor,anchor,areas or [anchor],self.pet_margins())
        else:
            corrected=clamp_center(self.app.pc,anchor,self.pet_margins())
        position_changed=corrected!=list(self.app.pc)
        if position_changed:
            self.app.pc=corrected
            self.app.geom()
            self.app._frame_key=None
            callback=getattr(self.app,"on_position_clamped",None)
            if callback:callback()
        enabled = self.app.conf.get("all_monitors", False)
        desired = set(areas) - {anchor} if enabled else set()
        topology = (tuple(areas), anchor, enabled)
        changed = topology != getattr(self, "_topology", None) or desired != set(self.mirrors)
        self._topology = topology
        for area in list(self.mirrors):
            if area not in desired:
                self.mirrors.pop(area).win.destroy()
        for area in sorted(desired):
            if area not in self.mirrors:
                win = tk.Toplevel(self.app.root)
                win.overrideredirect(True)
                win.attributes("-topmost", True)
                win.geometry("1x1+-32000+-32000")
                self.mirrors[area] = self.make_view(win, self.layered(win))
        return changed or position_changed

    def pet_margins(self):
        margins=getattr(self.app,"pet_margins",None)
        if margins is not None:return margins
        return (self.scale(self.app.pw+4),self.scale(max(self.app.ptop,50)+4))

    def drag_center(self, point, dx, dy):
        if not self.app.conf.get("all_monitors", False):
            proposed=[point[0]+dx,point[1]+dy]
            return clamp_center(proposed,self.work_area(proposed),self.pet_margins())
        anchor = self.work_area(point)
        return shared_drag(point, dx, dy, self.app._drag_source_area, anchor,
                           self.areas or [anchor],
                           self.pet_margins())

    def present(self, image=None, moving=False, images=None):
        if images is not None:
            self._area_images=images
            self.last_image=next(iter(images.values()))
            self._bbox_cache={}
        elif image is not None:
            self.last_image = image
            self._area_images={}
            self._bbox_cache={}
            self._image_bbox = None
        image = self.last_image
        if image is None:
            return
        self.sync()
        app = self.app
        anchor = self.work_area(app.pc)
        multi = app.conf.get("all_monitors", False)
        views = [(anchor, self.root_view)] + list(self.mirrors.items())
        crops = {}
        for area, view in views:
            image=getattr(self,"_area_images",{}).get(area,self.last_image)
            if image is None:continue
            cache=getattr(self,"_bbox_cache",None)
            if cache is None:self._bbox_cache={};cache=self._bbox_cache
            if multi and id(image) not in cache:cache[id(image)]=image.getbbox()
            bbox=cache.get(id(image)) if multi else None
            center = corresponding_center(app.pc, anchor, area) if multi else list(app.pc)
            x, y = center[0]-self.scale(app.cx), center[1]-self.scale(app.cy)
            crop = (0, 0, image.width, image.height)
            if multi:
                l, t, r, b = bbox or crop
                crop = (max(l, area[0]-x), max(t, area[1]-y),
                        min(r, area[2]-x), min(b, area[3]-y))
            if crop[2] <= crop[0] or crop[3] <= crop[1]:
                continue
            # Cropping keeps every copy within its own screen and reduces GDI uploads.
            rect = crop
            px, py = x+crop[0], y+crop[1]
            if moving and view.rect == rect:
                view.layer.move(px, py)
            else:
                cache_key=(id(image),crop)
                if cache_key not in crops:
                    crops[cache_key] = image if crop == (0, 0, image.width, image.height) else image.crop(crop)
                view.layer.show(crops[cache_key], px, py)
            view.rect, view.crop = rect, crop[:2]
            view.origin, view.center, view.area = (x, y), center, area
        menu=getattr(app,"menu",None)
        if menu is not None and menu.open_:
            menu.layer.topmost()

    def topmost(self):
        if self.sync():
            self.app._frame_key = None
            self.present()
        for view in [self.root_view] + list(self.mirrors.values()):
            view.layer.topmost()
