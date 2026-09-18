"""Projectable teacher scenes: a whole scene must not become a thin banner."""


def arrange_teacher_scene(layout):
    if "_scene_" not in layout["id"]:
        return
    count = int(layout["id"].rsplit("_", 1)[-1])
    components = {c["id"]: c for c in layout["components"]}
    scene = components["scene"]["elements"][0]
    kind = layout["id"].split("_scene_", 1)[1].rsplit("_", 1)[0]
    if not count:
        picture = (208, 174, 864, 432)
        area, columns = (48, 178, 1184, 430), 1
    elif kind == "top":
        picture = (280, 172, 720, 288)
        area, columns = (48, 482, 1184, 132), count
    elif kind == "roomy":
        picture = (848, 250, 384, 288)
        area, columns = (48, 178, 760, 430), 1 if count <= 3 else 2
    elif kind == "left":
        picture = (48, 178, 448, 430)
        area, columns = (536, 178, 696, 430), 1 if count <= 3 else 2
    else:
        picture = (784, 178, 448, 430)
        area, columns = (48, 178, 696, 430), 1 if count <= 3 else 2
    x, y, w, h = picture
    scene["position"], scene["size"] = {"x": x, "y": y}, {"width": w, "height": h}
    scene["fit"] = "contain"
    x, y, w, h = area
    rows = max(1, (count + columns - 1) // columns)
    width, height = (w - 24 * (columns - 1)) / columns, (h - 16 * (rows - 1)) / rows
    for index in range(count):
        row, column = divmod(index, columns)
        text = components[f"point_{index}"]["elements"][0]
        text["position"] = {"x": x + column * (width + 24), "y": y + row * (height + 16)}
        text["size"] = {"width": width, "height": height}
        text["alignment"]["vertical"] = "top"
