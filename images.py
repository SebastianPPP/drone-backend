# make_icons.py
from PIL import Image, ImageDraw

COLORS = {
    "marked":     (198, 40,  40, 255),   # czerwony
    "active":     ( 46,125,  50, 255),   # zielony
    "non_active": (117,117, 117, 255),   # szary
}

def boat(draw):
    """Rysuje prostą łódkę (trójkąt + kadłub)."""
    draw.polygon([(14,2),(2,16),(10,16)], fill=None)  # żagiel (niewypełniony, kontur)
    draw.polygon([(18,16),(26,16),(14,2)], fill=None)
    draw.rectangle([6,18,22,24], outline=None, width=0)  # kadłub

for name, rgba in COLORS.items():
    im = Image.new("RGBA", (28,28), (0,0,0,0))
    d  = ImageDraw.Draw(im)
    d.polygon([(14,2),(2,16),(10,16)], fill=rgba)        # żagiel lewy
    d.polygon([(14,2),(26,16),(18,16)], fill=rgba)       # żagiel prawy
    d.rectangle([6,18,22,24], fill=rgba)                 # kadłub
    im.save(f"{name}.png")
    print(f"{name}.png utworzony")
