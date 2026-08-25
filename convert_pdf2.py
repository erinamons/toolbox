import fitz
import os

SRC_DIR = r"D:/xwechat_files/wxid_479tvqbj3o6f22_5038/msg/file/2026-08"
OUT_DIR = r"D:/xwechat_files/wxid_479tvqbj3o6f22_5038/msg/file/2026-08/jpg_output"

FILES = [
    "1638867036459(1).pdf",
    "1647312077286.pdf",
    "1638867036461.pdf",
]

ZOOM = 2.0

os.makedirs(OUT_DIR, exist_ok=True)

for f in FILES:
    src = os.path.join(SRC_DIR, f)
    doc = fitz.open(src)
    base = os.path.splitext(f)[0]
    for i, page in enumerate(doc):
        mat = fitz.Matrix(ZOOM, ZOOM)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        if doc.page_count == 1:
            out_name = f"{base}.jpg"
        else:
            out_name = f"{base}_p{i+1}.jpg"
        out_path = os.path.join(OUT_DIR, out_name)
        pix.save(out_path)
        print(f"OK {out_name} ({pix.width}x{pix.height})")
    doc.close()

print("DONE")
