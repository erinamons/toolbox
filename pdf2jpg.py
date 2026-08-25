#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF → JPG 批量转换工具
========================
与 WorkBuddy 转换方式一致：
  - 2 倍分辨率渲染（约 1190x1684，清晰可打印）
  - 输出到每个 PDF 同目录下的 jpg_output 文件夹
  - 多页 PDF 自动按 _p1、_p2 ... 编号；单页直接同名

用法（任选其一）：
  1. 双击「PDF转JPG.bat」→ 弹出文件选择框，选一个或多个 PDF
  2. 把 PDF 文件（可多个）拖到「PDF转JPG.bat」图标上
  3. 命令行：python pdf2jpg.py a.pdf b.pdf
     python pdf2jpg.py "D:/某个文件夹"   # 转换文件夹内全部 PDF
     python pdf2jpg.py                    # 等同于双击（弹选择框）

依赖：PyMuPDF（首次运行会自动尝试安装）
"""
import glob
import os
import subprocess
import sys

ZOOM = 2.0  # 渲染倍率，越大越清晰、文件越大（可改 1.5 / 3.0）


def ensure_pymupdf():
    """确保 pymupdf 可用，缺失时自动 pip 安装。"""
    try:
        import pymupdf  # noqa: F401
        return pymupdf
    except ImportError:
        try:
            import fitz  # 兼容旧版包名
            return fitz
        except ImportError:
            pass
    print("[提示] 未检测到 PyMuPDF，正在自动安装 ...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf"])
        import pymupdf
        return pymupdf
    except Exception as e:
        print(f"[错误] 自动安装失败：{e}")
        print("请手动执行：pip install pymupdf")
        sys.exit(1)


def convert_pdf(pymupdf, src: str) -> list:
    """转换单个 PDF，返回生成的 JPG 绝对路径列表。"""
    src = os.path.abspath(src)
    out_dir = os.path.join(os.path.dirname(src), "jpg_output")
    os.makedirs(out_dir, exist_ok=True)

    doc = pymupdf.open(src)
    base = os.path.splitext(os.path.basename(src))[0]
    paths = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False)
            name = f"{base}.jpg" if doc.page_count == 1 else f"{base}_p{i + 1}.jpg"
            path = os.path.join(out_dir, name)
            pix.save(path)
            paths.append(path)
    finally:
        doc.close()
    return paths


def collect_pdfs(args) -> list:
    """把命令行参数解析为 PDF 文件列表（支持文件/文件夹，去重保序）。"""
    files = []
    for a in args:
        if os.path.isdir(a):
            files.extend(sorted(glob.glob(os.path.join(a, "*.pdf"))))
        elif os.path.isfile(a) and a.lower().endswith(".pdf"):
            files.append(a)
    seen, result = set(), []
    for f in files:
        k = os.path.abspath(f).lower()
        if k not in seen:
            seen.add(k)
            result.append(f)
    return result


def main():
    pymupdf = ensure_pymupdf()
    args = sys.argv[1:]

    if args:
        files = collect_pdfs(args)
    else:
        # 无参数 → 优先弹文件选择框；环境不支持时改为控制台输入路径
        files = []
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            files = filedialog.askopenfilenames(
                title="选择要转换的 PDF 文件（可多选）",
                filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
            )
            root.destroy()
        except Exception:
            print("无法打开文件选择框（当前 Python 无 tkinter 组件）。")
            print("建议：直接把 PDF 文件拖到 PDF转JPG.bat 图标上即可转换。")
            print("或者在此输入 PDF 文件路径后回车：")
            try:
                inp = input("> ").strip().strip('"')
            except EOFError:
                inp = ""
            if inp:
                files = [inp]

    if not files:
        print("没有可转换的 PDF 文件。")
        return

    ok, fail = 0, 0
    total_jpg = 0
    for f in files:
        try:
            paths = convert_pdf(pymupdf, f)
            ok += 1
            total_jpg += len(paths)
            print(f"[OK] {os.path.basename(f)} -> {len(paths)} 张")
            for p in paths:
                print(f"     {p}")
        except Exception as e:
            fail += 1
            print(f"[FAIL] {f}: {e}")

    print("-" * 50)
    print(f"完成：{ok} 个 PDF 转换成功，共生成 {total_jpg} 张 JPG，失败 {fail} 个。")
    print("输出目录：PDF 同目录下的 jpg_output/")


if __name__ == "__main__":
    main()
