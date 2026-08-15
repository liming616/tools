"""
生成一个简单的程序图标 (icon.ico)
在 Windows 上运行: python generate_icon.py
"""

from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 256


def generate():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角矩形背景
    margin = 10
    bg_color = (52, 152, 219)  # 蓝色
    draw.rounded_rectangle(
        [margin, margin, SIZE - margin, SIZE - margin],
        radius=40,
        fill=bg_color,
    )

    # 白色文字: 单
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 120)
    except OSError:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", 120)
        except OSError:
            font = ImageFont.load_default()

    text = "单"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - tw) // 2
    y = (SIZE - th) // 2 - 10
    draw.text((x, y), text, fill="white", font=font)

    # 保存为 ico（多尺寸）
    sizes = [256, 128, 64, 48, 32, 16]
    img.save("icon.ico", format="ICO", sizes=[(s, s) for s in sizes])
    print("✅ icon.ico 已生成")


if __name__ == "__main__":
    try:
        generate()
    except ImportError:
        print("⚠️  需要 Pillow 库: pip install Pillow")
        print("跳过图标生成，打包时将使用默认图标")
