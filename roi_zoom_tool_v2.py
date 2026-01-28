"""
Leo ROI Zoom Tool - 核心处理模块

作者: Leo Meng (Linghan Meng)
版本: 1.0
功能: 图像模板匹配、比例尺绘制、标注、水印等
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import argparse
from pathlib import Path
import platform


def get_default_font(size=20):
    """获取默认字体"""
    system = platform.system()
    font_paths = []

    if system == 'Darwin':  # macOS
        font_paths = [
            '/System/Library/Fonts/Helvetica.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/Library/Fonts/Arial.ttf',
        ]
    elif system == 'Windows':
        font_paths = [
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/msyh.ttc',
        ]
    else:  # Linux
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        ]

    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue

    # 回退到默认字体
    return ImageFont.load_default()


def find_roi_position(panorama_path: str, zoom_path: str) -> tuple:
    """
    使用模板匹配找到放大图在全景图中的位置
    """
    panorama = cv2.imread(panorama_path)
    zoom_img = cv2.imread(zoom_path)

    if panorama is None:
        raise ValueError(f"无法读取全景图: {panorama_path}")
    if zoom_img is None:
        raise ValueError(f"无法读取放大图: {zoom_path}")

    zoom_h, zoom_w = zoom_img.shape[:2]
    pano_h, pano_w = panorama.shape[:2]

    best_match = None
    best_confidence = -1

    scales = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1]

    for scale in scales:
        new_w = int(zoom_w * scale)
        new_h = int(zoom_h * scale)

        if new_w >= pano_w or new_h >= pano_h:
            continue
        if new_w < 10 or new_h < 10:
            continue

        template = cv2.resize(zoom_img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(panorama, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val > best_confidence:
            best_confidence = max_val
            best_match = (max_loc[0], max_loc[1], new_w, new_h, scale)

    if best_match is None:
        raise ValueError("无法找到匹配位置")

    x, y, w, h, scale = best_match
    return x, y, w, h, best_confidence


def draw_dashed_line(draw, start, end, color, width, dash_length=15, gap_length=10):
    """绘制虚线"""
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    length = (dx**2 + dy**2) ** 0.5

    if length == 0:
        return

    ux = dx / length
    uy = dy / length
    current_pos = 0
    drawing = True

    while current_pos < length:
        if drawing:
            seg_length = min(dash_length, length - current_pos)
            seg_start = (x1 + ux * current_pos, y1 + uy * current_pos)
            seg_end = (x1 + ux * (current_pos + seg_length), y1 + uy * (current_pos + seg_length))
            draw.line([seg_start, seg_end], fill=color, width=width)
            current_pos += dash_length
        else:
            current_pos += gap_length
        drawing = not drawing


def draw_scale_bar(draw, position, length_pixels, length_um, color=(0, 0, 0),
                   thickness=5, font_size=24, show_text=True, style='ends', font_family='Arial', text_gap=5):
    """
    绘制比例尺

    Args:
        draw: ImageDraw 对象
        position: 比例尺位置 (x, y) - 左下角
        length_pixels: 比例尺长度（像素）
        length_um: 比例尺代表的实际长度（微米）
        color: 颜色
        thickness: 线条粗细
        font_size: 字体大小
        show_text: 是否显示文字
        style: 样式 - 'line'(纯直线), 'ends'(两端竖线), 'ticks'(带刻度)
        font_family: 字体名称
        text_gap: 文字与比例尺的距离
    """
    x, y = position

    # 画横线
    draw.line([(x, y), (x + length_pixels, y)], fill=color, width=thickness)

    end_height = thickness * 3

    if style == 'ends':
        # 画两端的竖线
        draw.line([(x, y - end_height), (x, y + end_height)], fill=color, width=thickness)
        draw.line([(x + length_pixels, y - end_height), (x + length_pixels, y + end_height)],
                  fill=color, width=thickness)
    elif style == 'ticks':
        # 画两端的竖线和中间刻度
        draw.line([(x, y - end_height), (x, y + end_height)], fill=color, width=thickness)
        draw.line([(x + length_pixels, y - end_height), (x + length_pixels, y + end_height)],
                  fill=color, width=thickness)
        # 中间刻度
        mid_x = x + length_pixels // 2
        mid_height = end_height // 2
        draw.line([(mid_x, y - mid_height), (mid_x, y + mid_height)], fill=color, width=max(1, thickness // 2))
    # style == 'line' 时只画横线，不画竖线

    # 添加文字
    if show_text:
        font = get_font(font_family, font_size)
        if length_um >= 1000:
            text = f"{length_um/1000:.1f} mm"
        else:
            text = f"{length_um:.0f} μm"

        # 获取文字尺寸
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # 文字居中放在比例尺上方
        text_x = x + (length_pixels - text_width) // 2
        if style == 'line':
            text_y = y - text_height - text_gap
        else:
            text_y = y - end_height - text_height - text_gap
        draw.text((text_x, text_y), text, fill=color, font=font)


def get_font(font_family, font_size):
    """获取指定字体"""
    from PIL import ImageFont
    try:
        # 尝试加载指定字体
        font = ImageFont.truetype(font_family, font_size)
        return font
    except:
        pass

    # 尝试常见字体路径
    font_paths = [
        f"/System/Library/Fonts/{font_family}.ttf",
        f"/System/Library/Fonts/Supplemental/{font_family}.ttf",
        f"/Library/Fonts/{font_family}.ttf",
        f"C:/Windows/Fonts/{font_family}.ttf",
        f"/usr/share/fonts/truetype/{font_family.lower()}/{font_family}.ttf",
    ]

    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            return font
        except:
            continue

    # 回退到默认字体
    return get_default_font(font_size)


def draw_annotation(draw, annotation_type, position, color=(255, 0, 0), size=20,
                    thickness=3, text=None, font_size=16, direction='up'):
    """
    绘制标注

    Args:
        draw: ImageDraw 对象
        annotation_type: 标注类型 ('arrow', 'star', 'circle', 'triangle', 'text')
        position: 标注位置 (x, y)
        color: 颜色
        size: 标注大小
        thickness: 线条粗细
        text: 文字内容（用于 text 类型）
        font_size: 字体大小
        direction: 箭头方向 ('up', 'down', 'left', 'right')
    """
    x, y = position

    if annotation_type == 'arrow':
        # 绘制箭头
        arrow_length = size
        head_length = size // 3
        head_width = size // 4

        if direction == 'up':
            end_y = y - arrow_length
            draw.line([(x, y), (x, end_y)], fill=color, width=thickness)
            draw.polygon([(x, end_y), (x - head_width, end_y + head_length),
                         (x + head_width, end_y + head_length)], fill=color)
        elif direction == 'down':
            end_y = y + arrow_length
            draw.line([(x, y), (x, end_y)], fill=color, width=thickness)
            draw.polygon([(x, end_y), (x - head_width, end_y - head_length),
                         (x + head_width, end_y - head_length)], fill=color)
        elif direction == 'left':
            end_x = x - arrow_length
            draw.line([(x, y), (end_x, y)], fill=color, width=thickness)
            draw.polygon([(end_x, y), (end_x + head_length, y - head_width),
                         (end_x + head_length, y + head_width)], fill=color)
        elif direction == 'right':
            end_x = x + arrow_length
            draw.line([(x, y), (end_x, y)], fill=color, width=thickness)
            draw.polygon([(end_x, y), (end_x - head_length, y - head_width),
                         (end_x - head_length, y + head_width)], fill=color)

    elif annotation_type == 'star':
        # 绘制星号 *
        font = get_default_font(size * 2)
        draw.text((x - size//2, y - size), "*", fill=color, font=font)

    elif annotation_type == 'circle':
        # 绘制空心圆
        draw.ellipse([x - size, y - size, x + size, y + size],
                     outline=color, width=thickness)

    elif annotation_type == 'triangle':
        # 绘制三角形
        points = [
            (x, y - size),  # 顶点
            (x - size, y + size),  # 左下
            (x + size, y + size)   # 右下
        ]
        draw.polygon(points, outline=color, width=thickness)

    elif annotation_type == 'text' and text:
        # 绘制文字标注
        font = get_default_font(font_size)
        draw.text((x, y), text, fill=color, font=font)


def draw_watermark(image, text, position='bottom-right', opacity=128,
                   font_size=24, color=(128, 128, 128)):
    """
    添加水印

    Args:
        image: PIL Image 对象
        text: 水印文字
        position: 位置 ('bottom-right', 'bottom-left', 'top-right', 'top-left', 'center')
        opacity: 透明度 (0-255)
        font_size: 字体大小
        color: 颜色

    Returns:
        添加水印后的图像
    """
    # 创建透明图层
    watermark_layer = Image.new('RGBA', image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(watermark_layer)

    font = get_default_font(font_size)

    # 获取文字尺寸
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # 计算位置
    margin = 20
    img_width, img_height = image.size

    if position == 'bottom-right':
        x = img_width - text_width - margin
        y = img_height - text_height - margin
    elif position == 'bottom-left':
        x = margin
        y = img_height - text_height - margin
    elif position == 'top-right':
        x = img_width - text_width - margin
        y = margin
    elif position == 'top-left':
        x = margin
        y = margin
    else:  # center
        x = (img_width - text_width) // 2
        y = (img_height - text_height) // 2

    # 绘制水印
    watermark_color = (*color, opacity)
    draw.text((x, y), text, fill=watermark_color, font=font)

    # 合并图层
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    result = Image.alpha_composite(image, watermark_layer)
    return result.convert('RGB')


def create_zoom_figure(
    panorama_path: str,
    zoom_path: str,
    output_path: str,
    box_color: tuple = (255, 0, 0),
    box_thickness: int = 3,
    line_color: tuple = (255, 0, 0),
    line_thickness: int = 2,
    zoom_position: str = 'right',
    zoom_scale: float = 1.0,
    padding: int = 50,
    zoom_box_color: tuple = (255, 0, 0),
    zoom_box_thickness: int = 3,
    line_style: str = 'solid',
    dash_length: int = 15,
    gap_length: int = 10,
    roi_offset: tuple = (0, 0),  # 手动微调偏移
    scale_bar: dict = None,  # 比例尺设置
    annotations: list = None,  # 标注列表
    watermark: dict = None  # 水印设置
):
    """
    创建带局部放大的组合图（增强版）
    """
    # 找到ROI位置
    x, y, w, h, confidence = find_roi_position(panorama_path, zoom_path)

    # 应用手动偏移
    x += roi_offset[0]
    y += roi_offset[1]

    if confidence < 0.5:
        print(f"警告：匹配置信度较低 ({confidence:.4f})，结果可能不准确")

    # 读取图像
    panorama = Image.open(panorama_path).convert('RGB')
    zoom_img = Image.open(zoom_path).convert('RGB')

    # 缩放放大图
    if zoom_scale != 1.0:
        new_size = (int(zoom_img.width * zoom_scale), int(zoom_img.height * zoom_scale))
        zoom_img = zoom_img.resize(new_size, Image.Resampling.LANCZOS)

    pano_w, pano_h = panorama.size
    zoom_w, zoom_h = zoom_img.size

    # 边框边距
    margin = max(box_thickness, zoom_box_thickness) + 5

    # 计算画布尺寸
    if zoom_position == 'right':
        canvas_w = margin + pano_w + padding + zoom_w + margin
        canvas_h = margin + max(pano_h, zoom_h) + margin
        pano_pos = (margin, margin + (max(pano_h, zoom_h) - pano_h) // 2)
        zoom_pos = (margin + pano_w + padding, margin + (max(pano_h, zoom_h) - zoom_h) // 2)
    elif zoom_position == 'left':
        canvas_w = margin + zoom_w + padding + pano_w + margin
        canvas_h = margin + max(pano_h, zoom_h) + margin
        pano_pos = (margin + zoom_w + padding, margin + (max(pano_h, zoom_h) - pano_h) // 2)
        zoom_pos = (margin, margin + (max(pano_h, zoom_h) - zoom_h) // 2)
    elif zoom_position == 'bottom':
        canvas_w = margin + max(pano_w, zoom_w) + margin
        canvas_h = margin + pano_h + padding + zoom_h + margin
        pano_pos = (margin + (max(pano_w, zoom_w) - pano_w) // 2, margin)
        zoom_pos = (margin + (max(pano_w, zoom_w) - zoom_w) // 2, margin + pano_h + padding)
    else:  # top
        canvas_w = margin + max(pano_w, zoom_w) + margin
        canvas_h = margin + zoom_h + padding + pano_h + margin
        pano_pos = (margin + (max(pano_w, zoom_w) - pano_w) // 2, margin + zoom_h + padding)
        zoom_pos = (margin + (max(pano_w, zoom_w) - zoom_w) // 2, margin)

    # 创建画布
    canvas = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
    canvas.paste(panorama, pano_pos)
    canvas.paste(zoom_img, zoom_pos)

    draw = ImageDraw.Draw(canvas)

    # 在全景图周围画边框
    pano_border_x1 = pano_pos[0]
    pano_border_y1 = pano_pos[1]
    pano_border_x2 = pano_pos[0] + pano_w
    pano_border_y2 = pano_pos[1] + pano_h

    for i in range(zoom_box_thickness):
        draw.rectangle(
            [pano_border_x1 - i, pano_border_y1 - i, pano_border_x2 + i, pano_border_y2 + i],
            outline=zoom_box_color
        )

    # 在全景图上画选框
    box_x1 = pano_pos[0] + x
    box_y1 = pano_pos[1] + y
    box_x2 = box_x1 + w
    box_y2 = box_y1 + h

    for i in range(box_thickness):
        draw.rectangle(
            [box_x1 - i, box_y1 - i, box_x2 + i, box_y2 + i],
            outline=box_color
        )

    # 在放大图周围画边框
    zoom_box_x1 = zoom_pos[0]
    zoom_box_y1 = zoom_pos[1]
    zoom_box_x2 = zoom_pos[0] + zoom_w
    zoom_box_y2 = zoom_pos[1] + zoom_h

    for i in range(zoom_box_thickness):
        draw.rectangle(
            [zoom_box_x1 - i, zoom_box_y1 - i, zoom_box_x2 + i, zoom_box_y2 + i],
            outline=zoom_box_color
        )

    # 画引导线
    def draw_guide_line(start, end):
        if line_style == 'dashed':
            draw_dashed_line(draw, start, end, line_color, line_thickness, dash_length, gap_length)
        else:
            draw.line([start, end], fill=line_color, width=line_thickness)

    if zoom_position == 'right':
        draw_guide_line((box_x2, box_y1), (zoom_box_x1, zoom_box_y1))
        draw_guide_line((box_x2, box_y2), (zoom_box_x1, zoom_box_y2))
    elif zoom_position == 'left':
        draw_guide_line((box_x1, box_y1), (zoom_box_x2, zoom_box_y1))
        draw_guide_line((box_x1, box_y2), (zoom_box_x2, zoom_box_y2))
    elif zoom_position == 'bottom':
        draw_guide_line((box_x1, box_y2), (zoom_box_x1, zoom_box_y1))
        draw_guide_line((box_x2, box_y2), (zoom_box_x2, zoom_box_y1))
    else:  # top
        draw_guide_line((box_x1, box_y1), (zoom_box_x1, zoom_box_y2))
        draw_guide_line((box_x2, box_y1), (zoom_box_x2, zoom_box_y2))

    # 绘制比例尺（支持单个或多个）
    def draw_single_scale_bar(sb_config):
        if not sb_config or not sb_config.get('enabled'):
            return
        sb_position = sb_config.get('position', 'zoom')
        sb_corner = sb_config.get('corner', 'right')  # 'left' or 'right'
        sb_offset_x = sb_config.get('offset_x', 30)
        sb_offset_y = sb_config.get('offset_y', 30)
        sb_length_um = sb_config.get('length_um', 100)
        sb_pixels_per_um = sb_config.get('pixels_per_um', 1.0)
        sb_color = sb_config.get('color', (0, 0, 0))
        sb_thickness = sb_config.get('thickness', 5)
        sb_font_size = sb_config.get('font_size', 24)
        sb_style = sb_config.get('style', 'ends')
        sb_font_family = sb_config.get('font_family', 'Arial')
        sb_text_gap = sb_config.get('text_gap', 5)

        sb_length_pixels = int(sb_length_um * sb_pixels_per_um)

        if sb_position == 'panorama':
            if sb_corner == 'left':
                sb_x = pano_pos[0] + sb_offset_x
            else:
                sb_x = pano_pos[0] + pano_w - sb_length_pixels - sb_offset_x
            sb_y = pano_pos[1] + pano_h - sb_offset_y
        else:  # zoom
            if sb_corner == 'left':
                sb_x = zoom_pos[0] + sb_offset_x
            else:
                sb_x = zoom_pos[0] + zoom_w - sb_length_pixels - sb_offset_x
            sb_y = zoom_pos[1] + zoom_h - sb_offset_y

        draw_scale_bar(draw, (sb_x, sb_y), sb_length_pixels, sb_length_um,
                      sb_color, sb_thickness, sb_font_size, style=sb_style, font_family=sb_font_family, text_gap=sb_text_gap)

    if scale_bar:
        if isinstance(scale_bar, list):
            for sb in scale_bar:
                draw_single_scale_bar(sb)
        else:
            draw_single_scale_bar(scale_bar)

    # 绘制标注
    if annotations:
        for ann in annotations:
            ann_type = ann.get('type', 'arrow')
            ann_pos = ann.get('position', (0, 0))
            ann_target = ann.get('target', 'zoom')  # 'panorama' or 'zoom'

            # 转换为画布坐标
            if ann_target == 'panorama':
                abs_pos = (pano_pos[0] + ann_pos[0], pano_pos[1] + ann_pos[1])
            else:
                abs_pos = (zoom_pos[0] + ann_pos[0], zoom_pos[1] + ann_pos[1])

            draw_annotation(
                draw,
                ann_type,
                abs_pos,
                color=ann.get('color', (255, 0, 0)),
                size=ann.get('size', 20),
                thickness=ann.get('thickness', 3),
                text=ann.get('text'),
                font_size=ann.get('font_size', 16),
                direction=ann.get('direction', 'up')
            )

    # 添加水印
    if watermark and watermark.get('enabled'):
        canvas = draw_watermark(
            canvas,
            watermark.get('text', ''),
            watermark.get('position', 'bottom-right'),
            watermark.get('opacity', 128),
            watermark.get('font_size', 24),
            watermark.get('color', (128, 128, 128))
        )

    # 保存
    canvas.save(output_path, quality=95)
    print(f"图像已保存到: {output_path}")

    return canvas, {
        'roi_x': x,
        'roi_y': y,
        'roi_w': w,
        'roi_h': h,
        'confidence': confidence,
        'pano_pos': pano_pos,
        'zoom_pos': zoom_pos
    }


if __name__ == '__main__':
    print("ROI Zoom Tool V2 - 请使用 GUI 版本")
