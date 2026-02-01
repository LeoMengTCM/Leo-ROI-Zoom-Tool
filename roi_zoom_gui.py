#!/usr/bin/env python3
"""
Leo ROI Zoom Tool - 科研图像局部放大图制作工具

作者: Leo Meng (Linghan Meng)
版本: 2.0
功能: 自动识别ROI区域，生成带引导线的局部放大组合图
特性: 比例尺、标注、水印、批量处理、实时预览、快捷键支持
"""

import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
from PIL import Image, ImageTk
import os
import json
import tempfile
import re
import platform
from pathlib import Path
from copy import deepcopy

# 导入V2核心功能
from roi_zoom_tool_v2 import create_zoom_figure, draw_scale_bar, draw_annotation, draw_watermark

# 配置文件路径
CONFIG_FILE = Path(__file__).parent / '.roi_zoom_config.json'


# ============== 辅助类 ==============

class PreviewDebouncer:
    """防抖预览触发器"""
    def __init__(self, root, callback, delay=500):
        self.root = root
        self.callback = callback
        self.delay = delay
        self._job = None

    def trigger(self, *args):
        """触发预览（带防抖）"""
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(self.delay, self._execute)

    def _execute(self):
        self._job = None
        self.callback()

    def cancel(self):
        """取消待执行的预览"""
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None


class HistoryManager:
    """历史记录管理器（撤销/重做）"""
    def __init__(self, max_history=20):
        self.max_history = max_history
        self.history = []
        self.current_index = -1

    def push(self, state):
        """保存状态"""
        # 删除当前位置之后的历史
        if self.current_index < len(self.history) - 1:
            self.history = self.history[:self.current_index + 1]

        # 添加新状态
        self.history.append(deepcopy(state))

        # 限制历史长度
        if len(self.history) > self.max_history:
            self.history.pop(0)
        else:
            self.current_index += 1

    def undo(self):
        """撤销"""
        if self.can_undo():
            self.current_index -= 1
            return deepcopy(self.history[self.current_index])
        return None

    def redo(self):
        """重做"""
        if self.can_redo():
            self.current_index += 1
            return deepcopy(self.history[self.current_index])
        return None

    def can_undo(self):
        return self.current_index > 0

    def can_redo(self):
        return self.current_index < len(self.history) - 1

    def undo_count(self):
        return self.current_index

    def clear(self):
        self.history = []
        self.current_index = -1


class CollapsiblePanel(ttk.Frame):
    """可折叠面板"""
    def __init__(self, parent, title, **kwargs):
        super().__init__(parent, **kwargs)

        self.is_expanded = tk.BooleanVar(value=False)

        # 标题栏
        self.header = ttk.Frame(self)
        self.header.pack(fill=tk.X)

        self.toggle_btn = ttk.Button(
            self.header, text="▶ " + title,
            command=self.toggle
        )
        self.toggle_btn.pack(fill=tk.X, expand=True)

        # 内容区域
        self.content = ttk.Frame(self)
        self.title = title

    def toggle(self):
        if self.is_expanded.get():
            self.content.pack_forget()
            self.toggle_btn.configure(text="▶ " + self.title)
            self.is_expanded.set(False)
        else:
            self.content.pack(fill=tk.X, padx=5, pady=5)
            self.toggle_btn.configure(text="▼ " + self.title)
            self.is_expanded.set(True)

    def expand(self):
        if not self.is_expanded.get():
            self.toggle()

    def collapse(self):
        if self.is_expanded.get():
            self.toggle()


class ROIZoomGUI:
    """ROI Zoom Tool 图形界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("Leo ROI Zoom Tool - 科研图像局部放大图制作工具")
        self.root.geometry("1200x900")
        self.root.minsize(1000, 800)

        # 设置样式
        self.setup_styles()

        # 变量初始化
        self.panorama_path = tk.StringVar()
        self.zoom_path = tk.StringVar()
        self.position_var = tk.StringVar(value='right')
        self.padding_var = tk.IntVar(value=50)
        self.box_thickness_var = tk.IntVar(value=3)
        self.line_thickness_var = tk.IntVar(value=2)
        self.color_var = (255, 0, 0)  # 默认红色
        self.line_style_var = tk.StringVar(value='solid')  # 实线/虚线
        self.dash_length_var = tk.IntVar(value=15)
        self.gap_length_var = tk.IntVar(value=10)

        # ROI偏移量
        self.roi_offset_x = tk.IntVar(value=0)
        self.roi_offset_y = tk.IntVar(value=0)

        # 比例尺参数 - 全景图
        self.pano_scale_bar_enabled = tk.BooleanVar(value=False)
        self.pano_scale_bar_length_um = tk.DoubleVar(value=100)
        self.pano_scale_bar_pixels_per_um = tk.DoubleVar(value=1.0)
        self.pano_scale_bar_thickness = tk.IntVar(value=5)
        self.pano_scale_bar_font_size = tk.IntVar(value=24)
        self.pano_scale_bar_color = (0, 0, 0)
        self.pano_scale_bar_pos_x = tk.StringVar(value='右')  # 左/右
        self.pano_scale_bar_offset_x = tk.IntVar(value=30)  # X偏移
        self.pano_scale_bar_offset_y = tk.IntVar(value=30)  # Y偏移（距底部）

        # 比例尺参数 - 放大图
        self.zoom_scale_bar_enabled = tk.BooleanVar(value=False)
        self.zoom_scale_bar_length_um = tk.DoubleVar(value=100)
        self.zoom_scale_bar_pixels_per_um = tk.DoubleVar(value=1.0)
        self.zoom_scale_bar_thickness = tk.IntVar(value=5)
        self.zoom_scale_bar_font_size = tk.IntVar(value=24)
        self.zoom_scale_bar_color = (0, 0, 0)
        self.zoom_scale_bar_pos_x = tk.StringVar(value='右')  # 左/右
        self.zoom_scale_bar_offset_x = tk.IntVar(value=30)  # X偏移
        self.zoom_scale_bar_offset_y = tk.IntVar(value=30)  # Y偏移（距底部）

        # 比例尺通用设置
        self.scale_bar_sync_position = tk.BooleanVar(value=False)  # False=同步，True=独立
        self.scale_bar_style = tk.StringVar(value='line')  # 样式：line/ends/ticks
        self.scale_bar_font_family = tk.StringVar(value='Arial')  # 字体
        self.scale_bar_text_gap = tk.IntVar(value=5)  # 文字与比例尺的距离

        # 导出设置（保持上次选择）
        self.export_format = tk.StringVar(value='PNG')
        self.export_dpi = tk.IntVar(value=300)
        self.export_quality = tk.IntVar(value=95)

        # 标注参数
        self.annotations = []  # 标注列表
        self.current_annotation_tool = tk.StringVar(value='arrow')
        self.annotation_target = tk.StringVar(value='zoom')
        self.annotation_direction = tk.StringVar(value='up')
        self.annotation_size = tk.IntVar(value=20)
        self.annotation_color = (255, 0, 0)
        self.annotation_text = tk.StringVar(value='')
        self.adding_annotation = False  # 是否正在添加标注

        # 水印参数
        self.watermark_enabled = tk.BooleanVar(value=False)
        self.watermark_text = tk.StringVar(value='')
        self.watermark_position = tk.StringVar(value='右下')  # 使用中文显示值
        self.watermark_opacity = tk.IntVar(value=128)
        self.watermark_font_size = tk.IntVar(value=24)
        self.watermark_color = (128, 128, 128)

        self.result_image = None  # 存储生成的结果图
        self.temp_output_path = None  # 临时输出路径
        self.metadata = None  # 存储生成结果的元数据

        # 历史记录管理器
        self.history = HistoryManager(max_history=20)

        # 防抖预览
        self.debouncer = None

        # 加载默认设置
        self.load_config()

        # 创建界面
        self.create_widgets()

        # 设置防抖预览
        self.debouncer = PreviewDebouncer(self.root, self.auto_preview, delay=500)

        # 设置拖拽支持（如果 tkinterdnd2 可用）
        self.setup_drag_drop()

        # 设置快捷键
        self.setup_shortcuts()

        # 更新状态栏
        self.update_status()

    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()

        # 尝试使用更现代的主题
        available_themes = style.theme_names()
        if 'aqua' in available_themes:  # macOS
            style.theme_use('aqua')
        elif 'clam' in available_themes:
            style.theme_use('clam')

        # 自定义样式
        style.configure('Title.TLabel', font=('Helvetica', 14, 'bold'))
        style.configure('Section.TLabelframe.Label', font=('Helvetica', 11, 'bold'))
        style.configure('Action.TButton', font=('Helvetica', 11))
        style.configure('Status.TLabel', font=('Helvetica', 10))

    def setup_drag_drop(self):
        """设置拖拽支持"""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            # 如果支持拖拽，添加拖拽功能
            self.drag_drop_available = True
        except ImportError:
            self.drag_drop_available = False

    def setup_shortcuts(self):
        """设置快捷键"""
        # 检测操作系统
        is_mac = platform.system() == 'Darwin'
        modifier = 'Command' if is_mac else 'Control'

        # Ctrl/Cmd + G: 生成预览
        self.root.bind(f'<{modifier}-g>', lambda e: self.generate_preview())
        self.root.bind(f'<{modifier}-G>', lambda e: self.generate_preview())

        # Ctrl/Cmd + S: 保存图像
        self.root.bind(f'<{modifier}-s>', lambda e: self.save_image())
        self.root.bind(f'<{modifier}-S>', lambda e: self.save_image())

        # Ctrl/Cmd + Z: 撤销
        self.root.bind(f'<{modifier}-z>', lambda e: self.undo())

        # Ctrl/Cmd + Shift + Z: 重做
        self.root.bind(f'<{modifier}-Shift-z>', lambda e: self.redo())
        self.root.bind(f'<{modifier}-Shift-Z>', lambda e: self.redo())

        # Ctrl/Cmd + R: 重置ROI位置
        self.root.bind(f'<{modifier}-r>', lambda e: self.reset_roi_offset())
        self.root.bind(f'<{modifier}-R>', lambda e: self.reset_roi_offset())

        # Escape: 取消当前操作
        self.root.bind('<Escape>', lambda e: self.cancel_operation())

    def undo(self):
        """撤销操作"""
        state = self.history.undo()
        if state:
            self.restore_state(state)
            self.update_status()
            self.auto_preview()

    def redo(self):
        """重做操作"""
        state = self.history.redo()
        if state:
            self.restore_state(state)
            self.update_status()
            self.auto_preview()

    def save_state(self):
        """保存当前状态到历史"""
        state = {
            'roi_offset_x': self.roi_offset_x.get(),
            'roi_offset_y': self.roi_offset_y.get(),
            'annotations': deepcopy(self.annotations),
            'pano_scale_bar_enabled': self.pano_scale_bar_enabled.get(),
            'pano_scale_bar_length_um': self.pano_scale_bar_length_um.get(),
            'pano_scale_bar_pixels_per_um': self.pano_scale_bar_pixels_per_um.get(),
            'zoom_scale_bar_enabled': self.zoom_scale_bar_enabled.get(),
            'zoom_scale_bar_length_um': self.zoom_scale_bar_length_um.get(),
            'zoom_scale_bar_pixels_per_um': self.zoom_scale_bar_pixels_per_um.get(),
            'watermark_enabled': self.watermark_enabled.get(),
            'watermark_text': self.watermark_text.get(),
        }
        self.history.push(state)
        self.update_status()

    def restore_state(self, state):
        """从历史恢复状态"""
        self.roi_offset_x.set(state.get('roi_offset_x', 0))
        self.roi_offset_y.set(state.get('roi_offset_y', 0))
        self.annotations = deepcopy(state.get('annotations', []))
        self.pano_scale_bar_enabled.set(state.get('pano_scale_bar_enabled', False))
        self.pano_scale_bar_length_um.set(state.get('pano_scale_bar_length_um', 100))
        self.pano_scale_bar_pixels_per_um.set(state.get('pano_scale_bar_pixels_per_um', 1.0))
        self.zoom_scale_bar_enabled.set(state.get('zoom_scale_bar_enabled', False))
        self.zoom_scale_bar_length_um.set(state.get('zoom_scale_bar_length_um', 100))
        self.zoom_scale_bar_pixels_per_um.set(state.get('zoom_scale_bar_pixels_per_um', 1.0))
        self.watermark_enabled.set(state.get('watermark_enabled', False))
        self.watermark_text.set(state.get('watermark_text', ''))
        # 更新标注列表显示
        if hasattr(self, 'annotation_listbox'):
            self.update_annotation_listbox()

    def reset_roi_offset(self):
        """重置ROI偏移"""
        self.save_state()
        self.roi_offset_x.set(0)
        self.roi_offset_y.set(0)
        self.debouncer.trigger()

    def cancel_operation(self):
        """取消当前操作"""
        self.adding_annotation = False
        self.preview_canvas.configure(cursor='')
        self.update_status("操作已取消")

    def update_status(self, message=None):
        """更新状态栏"""
        if message:
            status_text = message
        else:
            undo_count = self.history.undo_count()
            status_text = f"就绪 | 可撤销: {undo_count}步"

        # 添加快捷键提示
        is_mac = platform.system() == 'Darwin'
        mod = "Cmd" if is_mac else "Ctrl"
        status_text += f" | {mod}+G生成 {mod}+S保存 {mod}+Z撤销"

        if hasattr(self, 'status_label'):
            self.status_label.configure(text=status_text)

    def auto_preview(self):
        """自动预览（如果两个图像都已选择）"""
        if self.panorama_path.get() and self.zoom_path.get():
            if os.path.exists(self.panorama_path.get()) and os.path.exists(self.zoom_path.get()):
                self.generate_preview()

    def load_config(self):
        """加载默认配置"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.position_var.set(config.get('position', 'right'))
                self.padding_var.set(config.get('padding', 50))
                self.box_thickness_var.set(config.get('box_thickness', 3))
                self.line_thickness_var.set(config.get('line_thickness', 2))
                self.color_var = tuple(config.get('color', [255, 0, 0]))
                self.line_style_var.set(config.get('line_style', 'solid'))
                self.dash_length_var.set(config.get('dash_length', 15))
                self.gap_length_var.set(config.get('gap_length', 10))

                # 比例尺配置 - 全景图
                pano_sb_config = config.get('pano_scale_bar', {})
                self.pano_scale_bar_enabled.set(pano_sb_config.get('enabled', False))
                self.pano_scale_bar_length_um.set(pano_sb_config.get('length_um', 100))
                self.pano_scale_bar_pixels_per_um.set(pano_sb_config.get('pixels_per_um', 1.0))
                self.pano_scale_bar_thickness.set(pano_sb_config.get('thickness', 5))
                self.pano_scale_bar_font_size.set(pano_sb_config.get('font_size', 24))
                self.pano_scale_bar_color = tuple(pano_sb_config.get('color', [0, 0, 0]))

                # 比例尺配置 - 放大图
                zoom_sb_config = config.get('zoom_scale_bar', {})
                self.zoom_scale_bar_enabled.set(zoom_sb_config.get('enabled', False))
                self.zoom_scale_bar_length_um.set(zoom_sb_config.get('length_um', 100))
                self.zoom_scale_bar_pixels_per_um.set(zoom_sb_config.get('pixels_per_um', 1.0))
                self.zoom_scale_bar_thickness.set(zoom_sb_config.get('thickness', 5))
                self.zoom_scale_bar_font_size.set(zoom_sb_config.get('font_size', 24))
                self.zoom_scale_bar_color = tuple(zoom_sb_config.get('color', [0, 0, 0]))

                # 水印配置
                watermark_config = config.get('watermark', {})
                self.watermark_enabled.set(watermark_config.get('enabled', False))
                self.watermark_text.set(watermark_config.get('text', ''))
                # 将英文位置值转换为中文显示值
                pos_en = watermark_config.get('position', 'bottom-right')
                pos_map_reverse = {
                    'bottom-right': '右下', 'bottom-left': '左下',
                    'top-right': '右上', 'top-left': '左上', 'center': '居中'
                }
                self.watermark_position.set(pos_map_reverse.get(pos_en, '右下'))
                self.watermark_opacity.set(watermark_config.get('opacity', 128))
                self.watermark_font_size.set(watermark_config.get('font_size', 24))
                self.watermark_color = tuple(watermark_config.get('color', [128, 128, 128]))

            except Exception as e:
                print(f"加载配置失败: {e}")

    def save_config(self):
        """保存当前设置为默认配置"""
        config = {
            'position': self.position_var.get(),
            'padding': self.padding_var.get(),
            'box_thickness': self.box_thickness_var.get(),
            'line_thickness': self.line_thickness_var.get(),
            'color': list(self.color_var),
            'line_style': self.line_style_var.get(),
            'dash_length': self.dash_length_var.get(),
            'gap_length': self.gap_length_var.get(),
            'pano_scale_bar': {
                'enabled': self.pano_scale_bar_enabled.get(),
                'length_um': self.pano_scale_bar_length_um.get(),
                'pixels_per_um': self.pano_scale_bar_pixels_per_um.get(),
                'thickness': self.pano_scale_bar_thickness.get(),
                'font_size': self.pano_scale_bar_font_size.get(),
                'color': list(self.pano_scale_bar_color),
            },
            'zoom_scale_bar': {
                'enabled': self.zoom_scale_bar_enabled.get(),
                'length_um': self.zoom_scale_bar_length_um.get(),
                'pixels_per_um': self.zoom_scale_bar_pixels_per_um.get(),
                'thickness': self.zoom_scale_bar_thickness.get(),
                'font_size': self.zoom_scale_bar_font_size.get(),
                'color': list(self.zoom_scale_bar_color),
            },
            'watermark': {
                'enabled': self.watermark_enabled.get(),
                'text': self.watermark_text.get(),
                'position': self.watermark_position_map.get(self.watermark_position.get(), 'bottom-right') if hasattr(self, 'watermark_position_map') else self.watermark_position.get(),
                'opacity': self.watermark_opacity.get(),
                'font_size': self.watermark_font_size.get(),
                'color': list(self.watermark_color),
            }
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("保存成功", "当前设置已保存为默认设置")
        except Exception as e:
            messagebox.showerror("保存失败", f"保存配置时出错:\n{str(e)}")

    def create_widgets(self):
        """创建所有界面组件"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(
            main_frame,
            text="Leo ROI Zoom Tool - 科研图像局部放大图制作工具",
            style='Title.TLabel'
        )
        title_label.pack(pady=(0, 10))

        # 创建左右分栏
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # 左侧：输入和参数（使用滚动区域）
        left_container = ttk.Frame(content_frame, width=400)
        left_container.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_container.pack_propagate(False)

        # 创建滚动画布
        self.left_canvas = tk.Canvas(left_container, highlightthickness=0, width=380)
        left_scrollbar = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=self.left_canvas.yview)
        self.left_frame = ttk.Frame(self.left_canvas)

        # 创建窗口并保存ID
        self.left_canvas_window = self.left_canvas.create_window((0, 0), window=self.left_frame, anchor="nw", width=380)

        # 配置滚动区域
        def configure_scroll(event):
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

        self.left_frame.bind("<Configure>", configure_scroll)
        self.left_canvas.configure(yscrollcommand=left_scrollbar.set)

        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定鼠标滚轮区域
        # 左侧设置面板滚动绑定
        self.left_canvas.bind('<Enter>', self._bind_left_scroll)
        self.left_canvas.bind('<Leave>', self._unbind_left_scroll)

        # 右侧：预览
        right_frame = ttk.Frame(content_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # === 左侧内容 ===
        self.create_input_section(self.left_frame)
        self.create_params_section(self.left_frame)
        self.create_scale_bar_panel(self.left_frame)
        self.create_annotation_panel(self.left_frame)
        self.create_watermark_panel(self.left_frame)
        self.create_action_section(self.left_frame)

        # === 右侧内容 ===
        self.create_preview_section(right_frame)

        # === 底部状态栏 ===
        self.create_status_bar(main_frame)

    def _bind_left_scroll(self, event):
        """绑定左侧面板滚动"""
        if platform.system() == 'Darwin':
            self.left_canvas.bind_all("<MouseWheel>", self._on_left_mousewheel)
        else:
            self.left_canvas.bind_all("<MouseWheel>", self._on_left_mousewheel)
            self.left_canvas.bind_all("<Button-4>", lambda e: self.left_canvas.yview_scroll(-1, "units"))
            self.left_canvas.bind_all("<Button-5>", lambda e: self.left_canvas.yview_scroll(1, "units"))

    def _unbind_left_scroll(self, event):
        """解绑左侧面板滚动"""
        if platform.system() == 'Darwin':
            self.left_canvas.unbind_all("<MouseWheel>")
        else:
            self.left_canvas.unbind_all("<MouseWheel>")
            self.left_canvas.unbind_all("<Button-4>")
            self.left_canvas.unbind_all("<Button-5>")

    def _on_left_mousewheel(self, event):
        """处理左侧面板滚动"""
        if platform.system() == 'Darwin':
            self.left_canvas.yview_scroll(int(-1 * event.delta), "units")
        else:
            self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def create_input_section(self, parent):
        """创建输入文件选择区域"""
        input_frame = ttk.LabelFrame(parent, text="输入图像", style='Section.TLabelframe', padding="10")
        input_frame.pack(fill=tk.X, pady=(0, 10))

        # 全景图选择
        pano_label_frame = ttk.Frame(input_frame)
        pano_label_frame.pack(fill=tk.X)
        ttk.Label(pano_label_frame, text="全景图:").pack(side=tk.LEFT)
        ttk.Button(pano_label_frame, text="选择...", command=self.select_panorama).pack(side=tk.RIGHT)

        pano_entry = ttk.Entry(input_frame, textvariable=self.panorama_path)
        pano_entry.pack(fill=tk.X, pady=(2, 5))

        # 全景图缩略图
        self.pano_thumb_label = ttk.Label(input_frame, text="[全景图预览]", anchor=tk.CENTER)
        self.pano_thumb_label.pack(fill=tk.X, pady=5)
        self.pano_thumb_label.configure(background='#f0f0f0')

        # 放大图选择
        zoom_label_frame = ttk.Frame(input_frame)
        zoom_label_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(zoom_label_frame, text="放大图:").pack(side=tk.LEFT)
        ttk.Button(zoom_label_frame, text="选择...", command=self.select_zoom).pack(side=tk.RIGHT)

        zoom_entry = ttk.Entry(input_frame, textvariable=self.zoom_path)
        zoom_entry.pack(fill=tk.X, pady=(2, 5))

        # 放大图缩略图
        self.zoom_thumb_label = ttk.Label(input_frame, text="[放大图预览]", anchor=tk.CENTER)
        self.zoom_thumb_label.pack(fill=tk.X, pady=5)
        self.zoom_thumb_label.configure(background='#f0f0f0')

    def create_params_section(self, parent):
        """创建参数设置区域"""
        params_frame = ttk.LabelFrame(parent, text="参数设置", style='Section.TLabelframe', padding="10")
        params_frame.pack(fill=tk.X, pady=(0, 10))

        # 拼接方向
        pos_frame = ttk.Frame(params_frame)
        pos_frame.pack(fill=tk.X, pady=5)

        ttk.Label(pos_frame, text="拼接方向:").pack(side=tk.LEFT)
        positions = [('右', 'right'), ('左', 'left'), ('上', 'top'), ('下', 'bottom')]
        for text, value in positions:
            ttk.Radiobutton(
                pos_frame, text=text, value=value,
                variable=self.position_var
            ).pack(side=tk.LEFT, padx=10)

        # 间距滑块
        padding_frame = ttk.Frame(params_frame)
        padding_frame.pack(fill=tk.X, pady=5)

        ttk.Label(padding_frame, text="间距:").pack(side=tk.LEFT)
        self.padding_label = ttk.Label(padding_frame, text="50", width=4)
        self.padding_label.pack(side=tk.RIGHT)
        padding_scale = ttk.Scale(
            padding_frame, from_=0, to=500,
            variable=self.padding_var, orient=tk.HORIZONTAL,
            command=lambda v: self.padding_label.configure(text=str(int(float(v))))
        )
        padding_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 边框线宽滑块
        box_frame = ttk.Frame(params_frame)
        box_frame.pack(fill=tk.X, pady=5)

        ttk.Label(box_frame, text="边框线宽:").pack(side=tk.LEFT)
        self.box_label = ttk.Label(box_frame, text="3", width=4)
        self.box_label.pack(side=tk.RIGHT)
        box_scale = ttk.Scale(
            box_frame, from_=1, to=20,
            variable=self.box_thickness_var, orient=tk.HORIZONTAL,
            command=lambda v: self.box_label.configure(text=str(int(float(v))))
        )
        box_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 引导线线宽滑块
        line_frame = ttk.Frame(params_frame)
        line_frame.pack(fill=tk.X, pady=5)

        ttk.Label(line_frame, text="引导线宽:").pack(side=tk.LEFT)
        self.line_label = ttk.Label(line_frame, text="2", width=4)
        self.line_label.pack(side=tk.RIGHT)
        line_scale = ttk.Scale(
            line_frame, from_=1, to=20,
            variable=self.line_thickness_var, orient=tk.HORIZONTAL,
            command=lambda v: self.line_label.configure(text=str(int(float(v))))
        )
        line_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 颜色选择
        color_frame = ttk.Frame(params_frame)
        color_frame.pack(fill=tk.X, pady=5)

        ttk.Label(color_frame, text="颜色:").pack(side=tk.LEFT)
        self.color_preview = tk.Canvas(color_frame, width=30, height=20, bg='#ff0000',
                                        highlightthickness=1, highlightbackground='gray')
        self.color_preview.pack(side=tk.LEFT, padx=10)
        ttk.Button(color_frame, text="选择颜色...", command=self.select_color).pack(side=tk.LEFT)
        self.color_hex_label = ttk.Label(color_frame, text="#FF0000")
        self.color_hex_label.pack(side=tk.LEFT, padx=10)

        # 更新颜色预览（根据加载的配置）
        color_hex = '#{:02x}{:02x}{:02x}'.format(*self.color_var)
        self.color_preview.configure(bg=color_hex)
        self.color_hex_label.configure(text=color_hex.upper())

        # 引导线样式
        style_frame = ttk.Frame(params_frame)
        style_frame.pack(fill=tk.X, pady=5)

        ttk.Label(style_frame, text="引导线样式:").pack(side=tk.LEFT)
        ttk.Radiobutton(style_frame, text="实线", value='solid',
                        variable=self.line_style_var,
                        command=self.toggle_dash_options).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(style_frame, text="虚线", value='dashed',
                        variable=self.line_style_var,
                        command=self.toggle_dash_options).pack(side=tk.LEFT, padx=10)

        # 虚线参数（默认隐藏）
        self.dash_frame = ttk.Frame(params_frame)
        self.dash_frame.pack(fill=tk.X, pady=5)

        ttk.Label(self.dash_frame, text="  虚线段长:").pack(side=tk.LEFT)
        self.dash_label = ttk.Label(self.dash_frame, text="15", width=4)
        self.dash_label.pack(side=tk.LEFT)
        dash_scale = ttk.Scale(
            self.dash_frame, from_=5, to=50,
            variable=self.dash_length_var, orient=tk.HORIZONTAL,
            command=lambda v: self.dash_label.configure(text=str(int(float(v))))
        )
        dash_scale.pack(side=tk.LEFT, padx=5)

        ttk.Label(self.dash_frame, text="间隔:").pack(side=tk.LEFT, padx=(10, 0))
        self.gap_label = ttk.Label(self.dash_frame, text="10", width=4)
        self.gap_label.pack(side=tk.LEFT)
        gap_scale = ttk.Scale(
            self.dash_frame, from_=3, to=30,
            variable=self.gap_length_var, orient=tk.HORIZONTAL,
            command=lambda v: self.gap_label.configure(text=str(int(float(v))))
        )
        gap_scale.pack(side=tk.LEFT, padx=5)

        # 根据当前样式显示/隐藏虚线参数
        self.toggle_dash_options()

    def toggle_dash_options(self):
        """切换虚线参数显示"""
        if self.line_style_var.get() == 'dashed':
            self.dash_frame.pack(fill=tk.X, pady=5)
        else:
            self.dash_frame.pack_forget()

    def create_scale_bar_panel(self, parent):
        """创建比例尺面板"""
        panel = CollapsiblePanel(parent, "比例尺")
        panel.pack(fill=tk.X, pady=(0, 5))

        content = panel.content

        # ===== 全景图比例尺 =====
        pano_frame = ttk.LabelFrame(content, text="全景图比例尺", padding="5")
        pano_frame.pack(fill=tk.X, pady=5)

        # 启用
        ttk.Checkbutton(
            pano_frame, text="启用",
            variable=self.pano_scale_bar_enabled,
            command=lambda: self.debouncer.trigger()
        ).pack(anchor=tk.W)

        # 全景图 - 实际长度
        pano_len_frame = ttk.Frame(pano_frame)
        pano_len_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pano_len_frame, text="长度(μm):").pack(side=tk.LEFT)
        ttk.Entry(pano_len_frame, textvariable=self.pano_scale_bar_length_um, width=8).pack(side=tk.LEFT, padx=5)
        for val in [50, 100, 200, 500]:
            ttk.Button(pano_len_frame, text=str(val), width=3,
                       command=lambda v=val: self.pano_scale_bar_length_um.set(v)).pack(side=tk.LEFT, padx=1)

        # 全景图 - 像素/微米比例
        pano_ratio_frame = ttk.Frame(pano_frame)
        pano_ratio_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pano_ratio_frame, text="像素/μm:").pack(side=tk.LEFT)
        ttk.Entry(pano_ratio_frame, textvariable=self.pano_scale_bar_pixels_per_um, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(pano_ratio_frame, text="计算", width=4,
                   command=lambda: self.open_ratio_calculator('pano')).pack(side=tk.LEFT)

        # 全景图 - 颜色
        pano_color_frame = ttk.Frame(pano_frame)
        pano_color_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pano_color_frame, text="颜色:").pack(side=tk.LEFT)
        self.pano_scale_bar_color_preview = tk.Canvas(
            pano_color_frame, width=20, height=15, bg='#000000',
            highlightthickness=1, highlightbackground='gray'
        )
        self.pano_scale_bar_color_preview.pack(side=tk.LEFT, padx=5)
        ttk.Button(pano_color_frame, text="选择", command=self.select_pano_scale_bar_color).pack(side=tk.LEFT)

        # ===== 放大图比例尺 =====
        zoom_frame = ttk.LabelFrame(content, text="放大图比例尺", padding="5")
        zoom_frame.pack(fill=tk.X, pady=5)

        # 启用
        ttk.Checkbutton(
            zoom_frame, text="启用",
            variable=self.zoom_scale_bar_enabled,
            command=lambda: self.debouncer.trigger()
        ).pack(anchor=tk.W)

        # 放大图 - 实际长度
        zoom_len_frame = ttk.Frame(zoom_frame)
        zoom_len_frame.pack(fill=tk.X, pady=2)
        ttk.Label(zoom_len_frame, text="长度(μm):").pack(side=tk.LEFT)
        ttk.Entry(zoom_len_frame, textvariable=self.zoom_scale_bar_length_um, width=8).pack(side=tk.LEFT, padx=5)
        for val in [10, 20, 50, 100]:
            ttk.Button(zoom_len_frame, text=str(val), width=3,
                       command=lambda v=val: self.zoom_scale_bar_length_um.set(v)).pack(side=tk.LEFT, padx=1)

        # 放大图 - 像素/微米比例
        zoom_ratio_frame = ttk.Frame(zoom_frame)
        zoom_ratio_frame.pack(fill=tk.X, pady=2)
        ttk.Label(zoom_ratio_frame, text="像素/μm:").pack(side=tk.LEFT)
        ttk.Entry(zoom_ratio_frame, textvariable=self.zoom_scale_bar_pixels_per_um, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(zoom_ratio_frame, text="计算", width=4,
                   command=lambda: self.open_ratio_calculator('zoom')).pack(side=tk.LEFT)

        # 放大图 - 颜色
        zoom_color_frame = ttk.Frame(zoom_frame)
        zoom_color_frame.pack(fill=tk.X, pady=2)
        ttk.Label(zoom_color_frame, text="颜色:").pack(side=tk.LEFT)
        self.zoom_scale_bar_color_preview = tk.Canvas(
            zoom_color_frame, width=20, height=15, bg='#000000',
            highlightthickness=1, highlightbackground='gray'
        )
        self.zoom_scale_bar_color_preview.pack(side=tk.LEFT, padx=5)
        ttk.Button(zoom_color_frame, text="选择", command=self.select_zoom_scale_bar_color).pack(side=tk.LEFT)

        # ===== 位置设置 =====
        pos_frame = ttk.LabelFrame(content, text="位置设置（通用）", padding="5")
        pos_frame.pack(fill=tk.X, pady=5)

        # 水平位置
        pos_x_frame = ttk.Frame(pos_frame)
        pos_x_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pos_x_frame, text="水平:").pack(side=tk.LEFT)
        ttk.Radiobutton(pos_x_frame, text="左", value='左',
                        variable=self.pano_scale_bar_pos_x,
                        command=self.on_scale_bar_pos_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(pos_x_frame, text="右", value='右',
                        variable=self.pano_scale_bar_pos_x,
                        command=self.on_scale_bar_pos_change).pack(side=tk.LEFT, padx=5)

        # X偏移
        offset_x_frame = ttk.Frame(pos_frame)
        offset_x_frame.pack(fill=tk.X, pady=2)
        ttk.Label(offset_x_frame, text="X偏移:").pack(side=tk.LEFT)
        ttk.Spinbox(offset_x_frame, from_=0, to=500, width=6,
                    textvariable=self.pano_scale_bar_offset_x,
                    command=self.on_scale_bar_pos_change).pack(side=tk.LEFT, padx=5)

        # Y偏移（距底部）
        offset_y_frame = ttk.Frame(pos_frame)
        offset_y_frame.pack(fill=tk.X, pady=2)
        ttk.Label(offset_y_frame, text="Y偏移(距底):").pack(side=tk.LEFT)
        ttk.Spinbox(offset_y_frame, from_=0, to=500, width=6,
                    textvariable=self.pano_scale_bar_offset_y,
                    command=self.on_scale_bar_pos_change).pack(side=tk.LEFT, padx=5)

        # 同步选项
        ttk.Checkbutton(
            pos_frame, text="全景图和放大图位置独立设置",
            variable=self.scale_bar_sync_position,
            command=self.on_scale_bar_sync_change
        ).pack(anchor=tk.W, pady=(5, 0))

        # ===== 通用设置 =====
        common_frame = ttk.LabelFrame(content, text="通用设置", padding="5")
        common_frame.pack(fill=tk.X, pady=5)

        # 样式选择
        style_frame = ttk.Frame(common_frame)
        style_frame.pack(fill=tk.X, pady=2)
        ttk.Label(style_frame, text="样式:").pack(side=tk.LEFT)
        styles = [
            ('纯直线', 'line'),
            ('两端竖线', 'ends'),
            ('带刻度', 'ticks'),
        ]
        for text, value in styles:
            ttk.Radiobutton(style_frame, text=text, value=value,
                            variable=self.scale_bar_style,
                            command=lambda: self.debouncer.trigger()).pack(side=tk.LEFT, padx=3)

        # 线宽
        thickness_frame = ttk.Frame(common_frame)
        thickness_frame.pack(fill=tk.X, pady=2)
        ttk.Label(thickness_frame, text="线宽:").pack(side=tk.LEFT)
        self.thickness_label = ttk.Label(thickness_frame, text="5", width=3)
        self.thickness_label.pack(side=tk.RIGHT)
        ttk.Scale(
            thickness_frame, from_=1, to=50,
            variable=self.pano_scale_bar_thickness, orient=tk.HORIZONTAL,
            command=lambda v: self.thickness_label.configure(text=str(int(float(v))))
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # 字体选择
        font_family_frame = ttk.Frame(common_frame)
        font_family_frame.pack(fill=tk.X, pady=2)
        ttk.Label(font_family_frame, text="字体:").pack(side=tk.LEFT)
        # 常用字体列表
        fonts = ['Arial', 'Helvetica', 'Times New Roman', 'Calibri', 'Georgia',
                 'Verdana', 'Courier New', 'SimHei', 'SimSun', 'Microsoft YaHei']
        font_combo = ttk.Combobox(font_family_frame, textvariable=self.scale_bar_font_family,
                                   values=fonts, width=15, state='readonly')
        font_combo.pack(side=tk.LEFT, padx=5)

        # 字体大小
        font_size_frame = ttk.Frame(common_frame)
        font_size_frame.pack(fill=tk.X, pady=2)
        ttk.Label(font_size_frame, text="字号:").pack(side=tk.LEFT)
        self.font_size_label = ttk.Label(font_size_frame, text="24", width=3)
        self.font_size_label.pack(side=tk.RIGHT)
        ttk.Scale(
            font_size_frame, from_=8, to=120,
            variable=self.pano_scale_bar_font_size, orient=tk.HORIZONTAL,
            command=lambda v: self.font_size_label.configure(text=str(int(float(v))))
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # 文字间距
        text_gap_frame = ttk.Frame(common_frame)
        text_gap_frame.pack(fill=tk.X, pady=2)
        ttk.Label(text_gap_frame, text="文字间距:").pack(side=tk.LEFT)
        self.text_gap_label = ttk.Label(text_gap_frame, text="5", width=3)
        self.text_gap_label.pack(side=tk.RIGHT)
        ttk.Scale(
            text_gap_frame, from_=0, to=50,
            variable=self.scale_bar_text_gap, orient=tk.HORIZONTAL,
            command=lambda v: self.text_gap_label.configure(text=str(int(float(v))))
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def on_scale_bar_sync_change(self):
        """比例尺同步选项变化"""
        self.debouncer.trigger()

    def on_scale_bar_pos_change(self):
        """比例尺位置变化 - 默认同时调整两个"""
        if not self.scale_bar_sync_position.get():
            # 同步到放大图
            self.zoom_scale_bar_pos_x.set(self.pano_scale_bar_pos_x.get())
            self.zoom_scale_bar_offset_x.set(self.pano_scale_bar_offset_x.get())
            self.zoom_scale_bar_offset_y.set(self.pano_scale_bar_offset_y.get())
        self.debouncer.trigger()

    def select_pano_scale_bar_color(self):
        """选择全景图比例尺颜色"""
        current_hex = '#{:02x}{:02x}{:02x}'.format(*self.pano_scale_bar_color)
        color = colorchooser.askcolor(color=current_hex, title='选择全景图比例尺颜色')
        if color[0]:
            self.pano_scale_bar_color = tuple(int(c) for c in color[0])
            self.pano_scale_bar_color_preview.configure(bg=color[1])

    def select_zoom_scale_bar_color(self):
        """选择放大图比例尺颜色"""
        current_hex = '#{:02x}{:02x}{:02x}'.format(*self.zoom_scale_bar_color)
        color = colorchooser.askcolor(color=current_hex, title='选择放大图比例尺颜色')
        if color[0]:
            self.zoom_scale_bar_color = tuple(int(c) for c in color[0])
            self.zoom_scale_bar_color_preview.configure(bg=color[1])

    def open_ratio_calculator(self, target):
        """打开像素/μm比例计算器"""
        RatioCalculatorDialog(self.root, self, target)

    def create_annotation_panel(self, parent):
        """创建标注面板"""
        panel = CollapsiblePanel(parent, "标注")
        panel.pack(fill=tk.X, pady=(0, 5))

        content = panel.content

        # 工具栏
        tools_frame = ttk.Frame(content)
        tools_frame.pack(fill=tk.X, pady=5)
        ttk.Label(tools_frame, text="工具:").pack(side=tk.LEFT)

        tools = [
            ('↑', 'arrow', '箭头'),
            ('★', 'star', '星号'),
            ('○', 'circle', '圆形'),
            ('△', 'triangle', '三角'),
            ('T', 'text', '文字'),
        ]
        for symbol, value, tip in tools:
            btn = ttk.Radiobutton(
                tools_frame, text=symbol, value=value,
                variable=self.current_annotation_tool, width=3
            )
            btn.pack(side=tk.LEFT, padx=2)

        # 目标选择
        target_frame = ttk.Frame(content)
        target_frame.pack(fill=tk.X, pady=5)
        ttk.Label(target_frame, text="添加到:").pack(side=tk.LEFT)
        ttk.Radiobutton(target_frame, text="全景图", value='panorama',
                        variable=self.annotation_target).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(target_frame, text="放大图", value='zoom',
                        variable=self.annotation_target).pack(side=tk.LEFT, padx=5)

        # 箭头方向
        dir_frame = ttk.Frame(content)
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Label(dir_frame, text="箭头方向:").pack(side=tk.LEFT)
        for text, value in [('上', 'up'), ('下', 'down'), ('左', 'left'), ('右', 'right')]:
            ttk.Radiobutton(dir_frame, text=text, value=value,
                            variable=self.annotation_direction).pack(side=tk.LEFT, padx=3)

        # 大小
        size_frame = ttk.Frame(content)
        size_frame.pack(fill=tk.X, pady=5)
        ttk.Label(size_frame, text="大小:").pack(side=tk.LEFT)
        ttk.Scale(
            size_frame, from_=10, to=100,
            variable=self.annotation_size, orient=tk.HORIZONTAL
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # 文字输入（用于文字标注）
        text_frame = ttk.Frame(content)
        text_frame.pack(fill=tk.X, pady=5)
        ttk.Label(text_frame, text="文字:").pack(side=tk.LEFT)
        ttk.Entry(text_frame, textvariable=self.annotation_text, width=15).pack(side=tk.LEFT, padx=5)

        # 颜色选择
        color_frame = ttk.Frame(content)
        color_frame.pack(fill=tk.X, pady=5)
        ttk.Label(color_frame, text="颜色:").pack(side=tk.LEFT)
        self.annotation_color_preview = tk.Canvas(
            color_frame, width=30, height=20, bg='#ff0000',
            highlightthickness=1, highlightbackground='gray'
        )
        self.annotation_color_preview.pack(side=tk.LEFT, padx=5)
        ttk.Button(
            color_frame, text="选择...",
            command=self.select_annotation_color
        ).pack(side=tk.LEFT)

        # 添加按钮
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(
            btn_frame, text="点击画布添加",
            command=self.start_adding_annotation
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            btn_frame, text="删除选中",
            command=self.delete_selected_annotation
        ).pack(side=tk.LEFT, padx=5)

        # 标注列表
        list_frame = ttk.Frame(content)
        list_frame.pack(fill=tk.X, pady=5)
        ttk.Label(list_frame, text="已添加标注:").pack(anchor=tk.W)

        self.annotation_listbox = tk.Listbox(list_frame, height=4, selectmode=tk.SINGLE)
        self.annotation_listbox.pack(fill=tk.X, pady=2)

    def select_annotation_color(self):
        """选择标注颜色"""
        current_hex = '#{:02x}{:02x}{:02x}'.format(*self.annotation_color)
        color = colorchooser.askcolor(color=current_hex, title='选择标注颜色')
        if color[0]:
            self.annotation_color = tuple(int(c) for c in color[0])
            self.annotation_color_preview.configure(bg=color[1])

    def start_adding_annotation(self):
        """开始添加标注模式"""
        if not self.result_image:
            messagebox.showwarning("警告", "请先生成预览图像")
            return

        self.adding_annotation = True
        self.preview_canvas.configure(cursor='crosshair')
        self.update_status("点击预览图添加标注，按Escape取消")

    def on_canvas_click(self, event):
        """处理画布点击事件"""
        if not self.adding_annotation:
            return

        # 获取点击位置（相对于画布）
        canvas_x = self.preview_canvas.canvasx(event.x)
        canvas_y = self.preview_canvas.canvasy(event.y)

        # 转换为图像坐标
        if hasattr(self, 'preview_scale') and self.preview_scale:
            img_x = int(canvas_x / self.preview_scale)
            img_y = int(canvas_y / self.preview_scale)
        else:
            img_x = int(canvas_x)
            img_y = int(canvas_y)

        # 确定是在全景图还是放大图区域
        if self.metadata:
            pano_pos = self.metadata.get('pano_pos', (0, 0))
            zoom_pos = self.metadata.get('zoom_pos', (0, 0))

            # 简化处理：根据用户选择的目标
            target = self.annotation_target.get()

            if target == 'panorama':
                rel_x = img_x - pano_pos[0]
                rel_y = img_y - pano_pos[1]
            else:
                rel_x = img_x - zoom_pos[0]
                rel_y = img_y - zoom_pos[1]

            # 创建标注
            annotation = {
                'type': self.current_annotation_tool.get(),
                'position': (rel_x, rel_y),
                'target': target,
                'color': self.annotation_color,
                'size': self.annotation_size.get(),
                'direction': self.annotation_direction.get(),
                'text': self.annotation_text.get() if self.current_annotation_tool.get() == 'text' else None,
            }

            self.save_state()
            self.annotations.append(annotation)
            self.update_annotation_listbox()

            # 退出添加模式
            self.adding_annotation = False
            self.preview_canvas.configure(cursor='')
            self.update_status()

            # 重新生成预览
            self.debouncer.trigger()

    def update_annotation_listbox(self):
        """更新标注列表显示"""
        self.annotation_listbox.delete(0, tk.END)
        for i, ann in enumerate(self.annotations):
            ann_type = ann.get('type', 'unknown')
            target = ann.get('target', 'zoom')
            pos = ann.get('position', (0, 0))
            self.annotation_listbox.insert(tk.END, f"{i+1}. {ann_type} @ {target} ({pos[0]}, {pos[1]})")

    def delete_selected_annotation(self):
        """删除选中的标注"""
        selection = self.annotation_listbox.curselection()
        if selection:
            self.save_state()
            idx = selection[0]
            del self.annotations[idx]
            self.update_annotation_listbox()
            self.debouncer.trigger()

    def create_watermark_panel(self, parent):
        """创建水印面板"""
        panel = CollapsiblePanel(parent, "水印")
        panel.pack(fill=tk.X, pady=(0, 5))

        content = panel.content

        # 启用复选框
        ttk.Checkbutton(
            content, text="启用水印",
            variable=self.watermark_enabled,
            command=lambda: self.debouncer.trigger()
        ).pack(anchor=tk.W)

        # 文字输入
        text_frame = ttk.Frame(content)
        text_frame.pack(fill=tk.X, pady=5)
        ttk.Label(text_frame, text="文字:").pack(side=tk.LEFT)
        ttk.Entry(text_frame, textvariable=self.watermark_text, width=20).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # 位置选择
        pos_frame = ttk.Frame(content)
        pos_frame.pack(fill=tk.X, pady=5)
        ttk.Label(pos_frame, text="位置:").pack(side=tk.LEFT)

        positions = [
            ('右下', 'bottom-right'),
            ('左下', 'bottom-left'),
            ('右上', 'top-right'),
            ('左上', 'top-left'),
            ('居中', 'center'),
        ]
        pos_combo = ttk.Combobox(
            pos_frame, textvariable=self.watermark_position,
            values=[p[0] for p in positions], state='readonly', width=8
        )
        pos_combo.pack(side=tk.LEFT, padx=5)
        # 设置映射
        self.watermark_position_map = {p[0]: p[1] for p in positions}
        self.watermark_position_map_reverse = {p[1]: p[0] for p in positions}

        # 透明度
        opacity_frame = ttk.Frame(content)
        opacity_frame.pack(fill=tk.X, pady=5)
        ttk.Label(opacity_frame, text="透明度:").pack(side=tk.LEFT)
        self.opacity_label = ttk.Label(opacity_frame, text="128", width=4)
        self.opacity_label.pack(side=tk.RIGHT)
        ttk.Scale(
            opacity_frame, from_=0, to=255,
            variable=self.watermark_opacity, orient=tk.HORIZONTAL,
            command=lambda v: self.opacity_label.configure(text=str(int(float(v))))
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # 字体大小
        font_frame = ttk.Frame(content)
        font_frame.pack(fill=tk.X, pady=5)
        ttk.Label(font_frame, text="字体大小:").pack(side=tk.LEFT)
        ttk.Scale(
            font_frame, from_=10, to=72,
            variable=self.watermark_font_size, orient=tk.HORIZONTAL
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # 颜色选择
        color_frame = ttk.Frame(content)
        color_frame.pack(fill=tk.X, pady=5)
        ttk.Label(color_frame, text="颜色:").pack(side=tk.LEFT)
        self.watermark_color_preview = tk.Canvas(
            color_frame, width=30, height=20, bg='#808080',
            highlightthickness=1, highlightbackground='gray'
        )
        self.watermark_color_preview.pack(side=tk.LEFT, padx=5)
        ttk.Button(
            color_frame, text="选择...",
            command=self.select_watermark_color
        ).pack(side=tk.LEFT)

    def select_watermark_color(self):
        """选择水印颜色"""
        current_hex = '#{:02x}{:02x}{:02x}'.format(*self.watermark_color)
        color = colorchooser.askcolor(color=current_hex, title='选择水印颜色')
        if color[0]:
            self.watermark_color = tuple(int(c) for c in color[0])
            self.watermark_color_preview.configure(bg=color[1])

    def create_status_bar(self, parent):
        """创建状态栏"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        self.status_label = ttk.Label(status_frame, text="就绪", style='Status.TLabel')
        self.status_label.pack(side=tk.LEFT)

        # 更新状态栏显示
        self.update_status()

    def create_action_section(self, parent):
        """创建操作按钮区域"""
        action_frame = ttk.Frame(parent, padding="10")
        action_frame.pack(fill=tk.X)

        # 第一行按钮
        row1 = ttk.Frame(action_frame)
        row1.pack(fill=tk.X, pady=2)

        # 生成按钮
        self.generate_btn = ttk.Button(
            row1, text="生成预览",
            command=self.generate_preview,
            style='Action.TButton'
        )
        self.generate_btn.pack(side=tk.LEFT, padx=5)

        # 保存按钮
        self.save_btn = ttk.Button(
            row1, text="保存图像",
            command=self.save_image,
            style='Action.TButton',
            state=tk.DISABLED
        )
        self.save_btn.pack(side=tk.LEFT, padx=5)

        # 第二行按钮
        row2 = ttk.Frame(action_frame)
        row2.pack(fill=tk.X, pady=2)

        # 批量处理按钮
        self.batch_btn = ttk.Button(
            row2, text="批量处理",
            command=self.open_batch_dialog,
            style='Action.TButton'
        )
        self.batch_btn.pack(side=tk.LEFT, padx=5)

        # 保存默认设置按钮
        self.save_config_btn = ttk.Button(
            row2, text="设为默认",
            command=self.save_config,
            style='Action.TButton'
        )
        self.save_config_btn.pack(side=tk.LEFT, padx=5)

    def create_preview_section(self, parent):
        """创建预览区域"""
        preview_frame = ttk.LabelFrame(parent, text="结果预览", style='Section.TLabelframe', padding="10")
        preview_frame.pack(fill=tk.BOTH, expand=True)

        # ROI偏移控制
        roi_frame = ttk.Frame(preview_frame)
        roi_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(roi_frame, text="ROI偏移:").pack(side=tk.LEFT)
        ttk.Label(roi_frame, text="X:").pack(side=tk.LEFT, padx=(10, 2))
        roi_x_spin = ttk.Spinbox(
            roi_frame, from_=-500, to=500, width=6,
            textvariable=self.roi_offset_x,
            command=lambda: self.debouncer.trigger()
        )
        roi_x_spin.pack(side=tk.LEFT)

        ttk.Label(roi_frame, text="Y:").pack(side=tk.LEFT, padx=(10, 2))
        roi_y_spin = ttk.Spinbox(
            roi_frame, from_=-500, to=500, width=6,
            textvariable=self.roi_offset_y,
            command=lambda: self.debouncer.trigger()
        )
        roi_y_spin.pack(side=tk.LEFT)

        ttk.Button(
            roi_frame, text="重置",
            command=self.reset_roi_offset
        ).pack(side=tk.LEFT, padx=10)

        # 缩放控制
        zoom_ctrl_frame = ttk.Frame(preview_frame)
        zoom_ctrl_frame.pack(fill=tk.X, pady=(5, 5))

        ttk.Label(zoom_ctrl_frame, text="预览缩放:").pack(side=tk.LEFT)
        self.preview_zoom_var = tk.DoubleVar(value=100)
        zoom_presets = [25, 50, 75, 100, 150, 200]
        for z in zoom_presets:
            ttk.Button(
                zoom_ctrl_frame, text=f"{z}%", width=4,
                command=lambda v=z: self.set_preview_zoom(v)
            ).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_ctrl_frame, text="适应", width=4,
                   command=self.fit_preview_to_canvas).pack(side=tk.LEFT, padx=5)

        self.zoom_label = ttk.Label(zoom_ctrl_frame, text="100%", width=5)
        self.zoom_label.pack(side=tk.RIGHT)

        # 预览画布（带滚动条）
        canvas_frame = ttk.Frame(preview_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        # 创建画布
        self.preview_canvas = tk.Canvas(canvas_frame, bg='#e0e0e0')
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定点击事件
        self.preview_canvas.bind('<Button-1>', self.on_left_down)
        self.preview_canvas.bind('<B1-Motion>', self.on_left_drag)
        self.preview_canvas.bind('<ButtonRelease-1>', self.on_canvas_click)  # Click triggered on release if not dragged

        # 绑定拖动事件
        self.preview_canvas.bind('<ButtonPress-2>', self.on_drag_start)  # 中键
        self.preview_canvas.bind('<B2-Motion>', self.on_drag_move)
        self.preview_canvas.bind('<ButtonPress-3>', self.on_drag_start)  # 右键也支持拖动
        self.preview_canvas.bind('<B3-Motion>', self.on_drag_move)

        # 绑定滚轮缩放
        self.preview_canvas.bind('<Control-MouseWheel>', self.on_zoom_wheel)
        self.preview_canvas.bind('<Command-MouseWheel>', self.on_zoom_wheel)  # macOS

        # 垂直滚动条
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.preview_canvas.yview)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 水平滚动条
        h_scrollbar = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self.preview_canvas.xview)
        h_scrollbar.pack(fill=tk.X)

        self.preview_canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # 绑定预览区域滚动
        self.preview_canvas.bind('<Enter>', self._bind_preview_scroll)
        self.preview_canvas.bind('<Leave>', self._unbind_preview_scroll)
        
        # 拖拽状态
        self._is_dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0

    def on_left_down(self, event):
        """左键按下"""
        if self.adding_annotation:
            # 如果是添加标注模式，不做任何事（等待释放时触发点击）
            pass
        else:
            # 否则开始拖动
            self._is_dragging = False  # 重置拖动标志
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self.on_drag_start(event)

    def on_left_drag(self, event):
        """左键拖动"""
        if self.adding_annotation:
            # 添加标注模式下不支持拖动
            return
        
        # 判断是否真的发生了移动（防抖动）
        if not self._is_dragging:
            if abs(event.x - self._drag_start_x) > 2 or abs(event.y - self._drag_start_y) > 2:
                self._is_dragging = True
        
        if self._is_dragging:
            self.on_drag_move(event)
            self.preview_canvas.configure(cursor='fleur')

    def _bind_preview_scroll(self, event):
        """绑定预览面板滚动"""
        # 注意：这里我们使用 bind_all 确保在画布区域内滚动生效，但仅当鼠标在画布上时
        if platform.system() == 'Darwin':
            self.preview_canvas.bind_all("<MouseWheel>", self._on_preview_mousewheel)
        else:
            self.preview_canvas.bind_all("<MouseWheel>", self._on_preview_mousewheel)
            self.preview_canvas.bind_all("<Button-4>", lambda e: self.preview_canvas.yview_scroll(-1, "units"))
            self.preview_canvas.bind_all("<Button-5>", lambda e: self.preview_canvas.yview_scroll(1, "units"))

    def _unbind_preview_scroll(self, event):
        """解绑预览面板滚动"""
        if platform.system() == 'Darwin':
            self.preview_canvas.unbind_all("<MouseWheel>")
        else:
            self.preview_canvas.unbind_all("<MouseWheel>")
            self.preview_canvas.unbind_all("<Button-4>")
            self.preview_canvas.unbind_all("<Button-5>")

    def _on_preview_mousewheel(self, event):
        """处理预览面板滚动"""
        # 如果按住了 Command/Control 键，则由缩放处理程序处理（不在此处理）
        state = event.state
        # macOS Command键通常是 8 或 16 (取决于具体修饰键组合)
        # Windows Control键是 4
        is_ctrl_cmd = (state & 4) or (state & 8) or (state & 16)
        
        if is_ctrl_cmd:
            return  # 交给 zoom handler

        # 检查是否按住 Shift 键进行水平滚动
        is_shift = (state & 1)
        
        if platform.system() == 'Darwin':
            delta = int(-1 * event.delta)
        else:
            delta = int(-1 * (event.delta / 120))
            
        if is_shift:
            self.preview_canvas.xview_scroll(delta, "units")
        else:
            self.preview_canvas.yview_scroll(delta, "units")

        # 初始提示文字
        self.preview_canvas.create_text(
            200, 150,
            text="生成的图像将在此处预览\n\n请先选择全景图和放大图，\n然后点击\"生成预览\"按钮",
            font=('Helvetica', 12),
            fill='#666666',
            justify=tk.CENTER
        )

        # 初始化预览缩放比例
        self.preview_scale = 1.0

    def select_panorama(self):
        """选择全景图文件"""
        filetypes = [
            ('图像文件', '*.png *.jpg *.jpeg *.tif *.tiff *.bmp'),
            ('所有文件', '*.*')
        ]
        path = filedialog.askopenfilename(
            title='选择全景图',
            filetypes=filetypes
        )
        if path:
            self.panorama_path.set(path)
            self.update_thumbnail(path, self.pano_thumb_label)

    def select_zoom(self):
        """选择放大图文件"""
        filetypes = [
            ('图像文件', '*.png *.jpg *.jpeg *.tif *.tiff *.bmp'),
            ('所有文件', '*.*')
        ]
        path = filedialog.askopenfilename(
            title='选择放大图',
            filetypes=filetypes
        )
        if path:
            self.zoom_path.set(path)
            self.update_thumbnail(path, self.zoom_thumb_label)

    def update_thumbnail(self, image_path, label, max_size=(200, 100)):
        """更新缩略图显示"""
        try:
            img = Image.open(image_path)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            label.configure(image=photo, text='')
            label.image = photo  # 保持引用
        except Exception as e:
            label.configure(image='', text=f'[无法加载: {e}]')

    def select_color(self):
        """打开颜色选择器"""
        # 将当前颜色转换为十六进制
        current_hex = '#{:02x}{:02x}{:02x}'.format(*self.color_var)

        color = colorchooser.askcolor(
            color=current_hex,
            title='选择颜色'
        )

        if color[0]:  # color[0] 是 RGB 元组，color[1] 是十六进制
            self.color_var = tuple(int(c) for c in color[0])
            self.color_preview.configure(bg=color[1])
            self.color_hex_label.configure(text=color[1].upper())

    def generate_preview(self):
        """生成预览图像"""
        # 验证输入
        if not self.panorama_path.get():
            messagebox.showerror("错误", "请选择全景图文件")
            return
        if not self.zoom_path.get():
            messagebox.showerror("错误", "请选择放大图文件")
            return

        if not os.path.exists(self.panorama_path.get()):
            messagebox.showerror("错误", f"全景图文件不存在: {self.panorama_path.get()}")
            return
        if not os.path.exists(self.zoom_path.get()):
            messagebox.showerror("错误", f"放大图文件不存在: {self.zoom_path.get()}")
            return

        # 更新状态
        self.update_status("正在生成...")
        self.generate_btn.configure(state=tk.DISABLED)
        self.root.update()

        try:
            # 创建临时输出文件
            self.temp_output_path = tempfile.mktemp(suffix='.png')

            # 准备比例尺参数 - 全景图
            pano_scale_bar_config = None
            if self.pano_scale_bar_enabled.get():
                pano_scale_bar_config = {
                    'enabled': True,
                    'position': 'panorama',
                    'corner': 'left' if self.pano_scale_bar_pos_x.get() == '左' else 'right',
                    'offset_x': self.pano_scale_bar_offset_x.get(),
                    'offset_y': self.pano_scale_bar_offset_y.get(),
                    'length_um': self.pano_scale_bar_length_um.get(),
                    'pixels_per_um': self.pano_scale_bar_pixels_per_um.get(),
                    'color': self.pano_scale_bar_color,
                    'thickness': self.pano_scale_bar_thickness.get(),
                    'font_size': self.pano_scale_bar_font_size.get(),
                    'style': self.scale_bar_style.get(),
                    'font_family': self.scale_bar_font_family.get(),
                    'text_gap': self.scale_bar_text_gap.get(),
                }

            # 准备比例尺参数 - 放大图
            zoom_scale_bar_config = None
            if self.zoom_scale_bar_enabled.get():
                zoom_scale_bar_config = {
                    'enabled': True,
                    'position': 'zoom',
                    'corner': 'left' if self.zoom_scale_bar_pos_x.get() == '左' else 'right',
                    'offset_x': self.zoom_scale_bar_offset_x.get(),
                    'offset_y': self.zoom_scale_bar_offset_y.get(),
                    'length_um': self.zoom_scale_bar_length_um.get(),
                    'pixels_per_um': self.zoom_scale_bar_pixels_per_um.get(),
                    'color': self.zoom_scale_bar_color,
                    'thickness': self.pano_scale_bar_thickness.get(),  # 使用通用设置
                    'font_size': self.pano_scale_bar_font_size.get(),  # 使用通用设置
                    'style': self.scale_bar_style.get(),
                    'font_family': self.scale_bar_font_family.get(),
                    'text_gap': self.scale_bar_text_gap.get(),
                }

            # 合并比例尺配置为列表
            scale_bars = []
            if pano_scale_bar_config:
                scale_bars.append(pano_scale_bar_config)
            if zoom_scale_bar_config:
                scale_bars.append(zoom_scale_bar_config)

            # 准备水印参数
            watermark_config = None
            if self.watermark_enabled.get() and self.watermark_text.get():
                # 处理位置映射
                pos = self.watermark_position.get()
                if hasattr(self, 'watermark_position_map') and pos in self.watermark_position_map:
                    pos = self.watermark_position_map[pos]
                watermark_config = {
                    'enabled': True,
                    'text': self.watermark_text.get(),
                    'position': pos,
                    'opacity': self.watermark_opacity.get(),
                    'font_size': self.watermark_font_size.get(),
                    'color': self.watermark_color,
                }

            # 调用V2核心函数
            result = create_zoom_figure(
                panorama_path=self.panorama_path.get(),
                zoom_path=self.zoom_path.get(),
                output_path=self.temp_output_path,
                box_color=self.color_var,
                box_thickness=self.box_thickness_var.get(),
                line_color=self.color_var,
                line_thickness=self.line_thickness_var.get(),
                zoom_position=self.position_var.get(),
                padding=self.padding_var.get(),
                zoom_box_color=self.color_var,
                zoom_box_thickness=self.box_thickness_var.get(),
                line_style=self.line_style_var.get(),
                dash_length=self.dash_length_var.get(),
                gap_length=self.gap_length_var.get(),
                roi_offset=(self.roi_offset_x.get(), self.roi_offset_y.get()),
                scale_bar=scale_bars[0] if len(scale_bars) == 1 else (scale_bars if scale_bars else None),
                annotations=self.annotations if self.annotations else None,
                watermark=watermark_config,
            )

            # V2返回元组 (image, metadata)
            if isinstance(result, tuple):
                self.result_image, self.metadata = result
            else:
                self.result_image = result
                self.metadata = None

            # 显示预览
            self.show_preview(self.result_image)

            # 启用保存按钮
            self.save_btn.configure(state=tk.NORMAL)
            self.update_status("生成完成")

        except Exception as e:
            messagebox.showerror("生成失败", f"生成图像时出错:\n{str(e)}")
            self.update_status("生成失败")
        finally:
            self.generate_btn.configure(state=tk.NORMAL)

    def show_preview(self, image, zoom_percent=None):
        """在预览区域显示图像（支持缩放和滚动）"""
        # 清除画布
        self.preview_canvas.delete("all")

        # 保存原始图像
        self.preview_original_image = image

        # 图像原始尺寸
        img_width, img_height = image.size

        # 确定缩放比例
        if zoom_percent is None:
            zoom_percent = self.preview_zoom_var.get()

        scale = zoom_percent / 100.0
        self.preview_scale = scale

        # 计算显示尺寸
        display_width = int(img_width * scale)
        display_height = int(img_height * scale)

        # 缩放图像
        if scale != 1.0:
            display_image = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        else:
            display_image = image

        # 转换为 PhotoImage
        photo = ImageTk.PhotoImage(display_image)

        # 设置滚动区域
        self.preview_canvas.configure(scrollregion=(0, 0, display_width, display_height))

        # 显示图像
        self.preview_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        self.preview_canvas.image = photo  # 保持引用

        # 更新缩放标签
        self.zoom_label.configure(text=f"{int(zoom_percent)}%")

    def set_preview_zoom(self, zoom_percent):
        """设置预览缩放比例"""
        self.preview_zoom_var.set(zoom_percent)
        if hasattr(self, 'preview_original_image') and self.preview_original_image:
            self.show_preview(self.preview_original_image, zoom_percent)

    def fit_preview_to_canvas(self):
        """适应画布大小"""
        if not hasattr(self, 'preview_original_image') or not self.preview_original_image:
            return

        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        img_width, img_height = self.preview_original_image.size

        # 计算适合的缩放比例
        scale = min(canvas_width / img_width, canvas_height / img_height)
        zoom_percent = scale * 100

        self.set_preview_zoom(zoom_percent)

    def on_drag_start(self, event):
        """开始拖动"""
        self.preview_canvas.scan_mark(event.x, event.y)

    def on_drag_move(self, event):
        """拖动移动"""
        self.preview_canvas.scan_dragto(event.x, event.y, gain=1)

    def on_zoom_wheel(self, event):
        """滚轮缩放"""
        if not hasattr(self, 'preview_original_image') or not self.preview_original_image:
            return

        current_zoom = self.preview_zoom_var.get()

        # 计算新的缩放比例
        if event.delta > 0:
            new_zoom = min(current_zoom * 1.2, 400)
        else:
            new_zoom = max(current_zoom / 1.2, 10)

        self.set_preview_zoom(new_zoom)

    def on_canvas_click(self, event):
        """处理画布点击事件（释放时触发）"""
        self.preview_canvas.configure(cursor='')  # Reset cursor
        
        # 如果刚才发生了拖拽，则忽略这次点击
        if hasattr(self, '_is_dragging') and self._is_dragging:
            self._is_dragging = False
            return
            
        if not self.adding_annotation:
            return

        # 获取点击位置（相对于画布）
        canvas_x = self.preview_canvas.canvasx(event.x)
        canvas_y = self.preview_canvas.canvasy(event.y)

        # 转换为图像坐标
        if hasattr(self, 'preview_scale') and self.preview_scale:
            img_x = int(canvas_x / self.preview_scale)
            img_y = int(canvas_y / self.preview_scale)
        else:
            img_x = int(canvas_x)
            img_y = int(canvas_y)

        # 确定是在全景图还是放大图区域
        if self.metadata:
            pano_pos = self.metadata.get('pano_pos', (0, 0))
            zoom_pos = self.metadata.get('zoom_pos', (0, 0))

            # 简化处理：根据用户选择的目标
            target = self.annotation_target.get()

            if target == 'panorama':
                rel_x = img_x - pano_pos[0]
                rel_y = img_y - pano_pos[1]
            else:
                rel_x = img_x - zoom_pos[0]
                rel_y = img_y - zoom_pos[1]

            # 创建标注
            annotation = {
                'type': self.current_annotation_tool.get(),
                'position': (rel_x, rel_y),
                'target': target,
                'color': self.annotation_color,
                'size': self.annotation_size.get(),
                'direction': self.annotation_direction.get(),
                'text': self.annotation_text.get() if self.current_annotation_tool.get() == 'text' else None,
            }

            self.save_state()
            self.annotations.append(annotation)
            self.update_annotation_listbox()

            # 退出添加模式
            self.adding_annotation = False
            self.preview_canvas.configure(cursor='')
            self.update_status()

            # 重新生成预览
            self.debouncer.trigger()

    def save_image(self):
        """打开导出对话框"""
        if self.result_image is None:
            messagebox.showerror("错误", "没有可保存的图像，请先生成预览")
            return

        # 打开导出对话框，传递GUI实例以保存设置
        ExportDialog(self.root, self.result_image, self.panorama_path.get(), self)

    def open_batch_dialog(self):
        """打开批量处理对话框"""
        BatchProcessDialog(self.root, self)


class ExportDialog:
    """导出对话框"""

    def __init__(self, parent, image, source_path, gui_instance=None):
        self.image = image
        self.source_path = source_path
        self.gui = gui_instance

        # 创建对话框窗口
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("导出图像")
        self.dialog.geometry("450x500")
        self.dialog.resizable(True, True)
        self.dialog.minsize(400, 450)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 变量 - 使用GUI实例中保存的值
        if gui_instance:
            self.format_var = gui_instance.export_format
            self.dpi_var = gui_instance.export_dpi
            self.quality_var = gui_instance.export_quality
        else:
            self.format_var = tk.StringVar(value='PNG')
            self.dpi_var = tk.IntVar(value=300)
            self.quality_var = tk.IntVar(value=95)

        self.create_widgets()

        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """创建对话框组件"""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 图像信息
        info_frame = ttk.LabelFrame(main_frame, text="图像信息", padding="10")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        width, height = self.image.size
        ttk.Label(info_frame, text=f"尺寸: {width} x {height} 像素").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"模式: {self.image.mode}").pack(anchor=tk.W)

        # 格式选择
        format_frame = ttk.LabelFrame(main_frame, text="导出格式", padding="10")
        format_frame.pack(fill=tk.X, pady=(0, 10))

        formats = [
            ('PNG (无损，推荐)', 'PNG'),
            ('JPEG (有损，文件小)', 'JPEG'),
            ('TIFF (无损，兼容性好)', 'TIFF'),
            ('BMP (无损，无压缩)', 'BMP')
        ]
        for text, value in formats:
            ttk.Radiobutton(
                format_frame, text=text, value=value,
                variable=self.format_var,
                command=self.toggle_quality
            ).pack(anchor=tk.W)

        # DPI 设置
        dpi_frame = ttk.LabelFrame(main_frame, text="分辨率 (DPI)", padding="10")
        dpi_frame.pack(fill=tk.X, pady=(0, 10))

        # DPI 预设 - 分两行显示
        dpi_row1 = ttk.Frame(dpi_frame)
        dpi_row1.pack(fill=tk.X)
        dpi_row2 = ttk.Frame(dpi_frame)
        dpi_row2.pack(fill=tk.X, pady=(5, 0))

        dpi_presets = [('72 (屏幕)', 72), ('150 (普通)', 150), ('300 (打印)', 300), ('600 (高清)', 600)]
        for i, (text, value) in enumerate(dpi_presets):
            parent_row = dpi_row1 if i < 2 else dpi_row2
            ttk.Radiobutton(
                parent_row, text=text, value=value,
                variable=self.dpi_var
            ).pack(side=tk.LEFT, padx=(0, 20))

        # 自定义 DPI
        custom_frame = ttk.Frame(dpi_frame)
        custom_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(custom_frame, text="自定义 DPI:").pack(side=tk.LEFT)
        self.dpi_entry = ttk.Entry(custom_frame, width=8)
        self.dpi_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(custom_frame, text="应用", command=self.apply_custom_dpi).pack(side=tk.LEFT)

        # JPEG 质量（仅 JPEG 格式显示）
        self.quality_frame = ttk.LabelFrame(main_frame, text="JPEG 质量", padding="10")

        quality_inner = ttk.Frame(self.quality_frame)
        quality_inner.pack(fill=tk.X)

        ttk.Label(quality_inner, text="质量 (1-100):").pack(side=tk.LEFT)
        quality_scale = ttk.Scale(
            quality_inner, from_=1, to=100,
            variable=self.quality_var, orient=tk.HORIZONTAL,
            command=lambda v: self.quality_label.configure(text=str(int(float(v))))
        )
        quality_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.quality_label = ttk.Label(quality_inner, text="95", width=4)
        self.quality_label.pack(side=tk.LEFT)

        # 按钮容器（固定在底部）
        self.btn_frame = ttk.Frame(main_frame)
        self.btn_frame.pack(fill=tk.X, pady=(20, 0), side=tk.BOTTOM)

        ttk.Button(self.btn_frame, text="导出", command=self.export).pack(side=tk.RIGHT, padx=5)
        ttk.Button(self.btn_frame, text="取消", command=self.dialog.destroy).pack(side=tk.RIGHT)

    def toggle_quality(self):
        """切换 JPEG 质量选项显示"""
        if self.format_var.get() == 'JPEG':
            self.quality_frame.pack(fill=tk.X, pady=(0, 10), before=self.btn_frame)
        else:
            self.quality_frame.pack_forget()

    def apply_custom_dpi(self):
        """应用自定义 DPI"""
        try:
            dpi = int(self.dpi_entry.get())
            if 1 <= dpi <= 2400:
                self.dpi_var.set(dpi)
            else:
                messagebox.showwarning("警告", "DPI 应在 1-2400 之间")
        except ValueError:
            messagebox.showwarning("警告", "请输入有效的数字")

    def export(self):
        """执行导出"""
        fmt = self.format_var.get()
        dpi = self.dpi_var.get()

        # 文件扩展名映射
        ext_map = {'PNG': '.png', 'JPEG': '.jpg', 'TIFF': '.tif', 'BMP': '.bmp'}
        ext = ext_map[fmt]

        # 默认文件名
        pano_name = Path(self.source_path).stem if self.source_path else 'output'
        default_name = f"{pano_name}_zoom_output{ext}"

        # 文件类型过滤
        filetypes = [(f'{fmt} 图像', f'*{ext}'), ('所有文件', '*.*')]

        save_path = filedialog.asksaveasfilename(
            parent=self.dialog,
            title='导出图像',
            defaultextension=ext,
            initialfile=default_name,
            filetypes=filetypes
        )

        if save_path:
            try:
                # 准备保存参数
                save_kwargs = {'dpi': (dpi, dpi)}

                if fmt == 'PNG':
                    self.image.save(save_path, 'PNG', **save_kwargs)
                elif fmt == 'JPEG':
                    # JPEG 不支持透明，转换为 RGB
                    if self.image.mode in ('RGBA', 'LA', 'P'):
                        rgb_image = self.image.convert('RGB')
                        rgb_image.save(save_path, 'JPEG', quality=self.quality_var.get(), **save_kwargs)
                    else:
                        self.image.save(save_path, 'JPEG', quality=self.quality_var.get(), **save_kwargs)
                elif fmt == 'TIFF':
                    self.image.save(save_path, 'TIFF', **save_kwargs)
                elif fmt == 'BMP':
                    # BMP 不支持 DPI 元数据，直接保存
                    self.image.save(save_path, 'BMP')

                messagebox.showinfo("导出成功", f"图像已导出到:\n{save_path}\n\n格式: {fmt}\nDPI: {dpi}")
                self.dialog.destroy()

            except Exception as e:
                messagebox.showerror("导出失败", f"导出图像时出错:\n{str(e)}")


class BatchProcessDialog:
    """批量处理对话框"""

    def __init__(self, parent, gui_instance):
        self.parent = parent
        self.gui = gui_instance
        self.file_pairs = []  # [(panorama_path, zoom_path), ...]
        self.processing = False

        # 创建对话框窗口
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("批量处理")
        self.dialog.geometry("700x600")
        self.dialog.minsize(600, 500)
        self.dialog.transient(parent)

        # 变量
        self.output_dir = tk.StringVar()
        self.naming_pattern = tk.StringVar(value='{name}_zoom')
        self.output_format = tk.StringVar(value='PNG')
        self.auto_match_pattern = tk.StringVar(value='suffix')

        self.create_widgets()

        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """创建对话框组件"""
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 文件列表区域
        list_frame = ttk.LabelFrame(main_frame, text="文件对列表", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 工具栏
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text="手动添加", command=self.add_pair_manual).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="从文件夹导入", command=self.import_from_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除选中", command=self.remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="清空列表", command=self.clear_list).pack(side=tk.LEFT, padx=2)

        # Treeview
        columns = ('panorama', 'zoom', 'status')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        self.tree.heading('panorama', text='全景图')
        self.tree.heading('zoom', text='放大图')
        self.tree.heading('status', text='状态')
        self.tree.column('panorama', width=250)
        self.tree.column('zoom', width=250)
        self.tree.column('status', width=80)

        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 自动匹配设置
        match_frame = ttk.LabelFrame(main_frame, text="自动匹配规则", padding="10")
        match_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(match_frame, text="匹配模式:").pack(side=tk.LEFT)
        patterns = [
            ('倍率后缀 (10x/40x)', 'suffix'),
            ('pano/zoom后缀', 'pano_zoom'),
            ('自定义正则', 'regex'),
        ]
        for text, value in patterns:
            ttk.Radiobutton(match_frame, text=text, value=value,
                            variable=self.auto_match_pattern).pack(side=tk.LEFT, padx=10)

        # 输出设置
        output_frame = ttk.LabelFrame(main_frame, text="输出设置", padding="10")
        output_frame.pack(fill=tk.X, pady=(0, 10))

        # 输出目录
        dir_frame = ttk.Frame(output_frame)
        dir_frame.pack(fill=tk.X, pady=2)
        ttk.Label(dir_frame, text="输出目录:").pack(side=tk.LEFT)
        ttk.Entry(dir_frame, textvariable=self.output_dir, width=40).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(dir_frame, text="选择...", command=self.select_output_dir).pack(side=tk.LEFT)

        # 命名模式
        name_frame = ttk.Frame(output_frame)
        name_frame.pack(fill=tk.X, pady=2)
        ttk.Label(name_frame, text="命名模式:").pack(side=tk.LEFT)
        ttk.Entry(name_frame, textvariable=self.naming_pattern, width=20).pack(side=tk.LEFT, padx=5)
        ttk.Label(name_frame, text="({name}=原文件名)").pack(side=tk.LEFT)

        # 输出格式
        fmt_frame = ttk.Frame(output_frame)
        fmt_frame.pack(fill=tk.X, pady=2)
        ttk.Label(fmt_frame, text="输出格式:").pack(side=tk.LEFT)
        for fmt in ['PNG', 'JPEG', 'TIFF']:
            ttk.Radiobutton(fmt_frame, text=fmt, value=fmt,
                            variable=self.output_format).pack(side=tk.LEFT, padx=10)

        # 进度条
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X)

        self.progress_label = ttk.Label(progress_frame, text="就绪")
        self.progress_label.pack(anchor=tk.W)

        # 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        self.start_btn = ttk.Button(btn_frame, text="开始处理", command=self.start_processing)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.cancel_btn = ttk.Button(btn_frame, text="取消", command=self.cancel_processing, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="关闭", command=self.dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def add_pair_manual(self):
        """手动添加文件对"""
        filetypes = [('图像文件', '*.png *.jpg *.jpeg *.tif *.tiff *.bmp'), ('所有文件', '*.*')]

        panorama = filedialog.askopenfilename(title='选择全景图', filetypes=filetypes)
        if not panorama:
            return

        zoom = filedialog.askopenfilename(title='选择放大图', filetypes=filetypes)
        if not zoom:
            return

        self.file_pairs.append((panorama, zoom))
        self.tree.insert('', tk.END, values=(Path(panorama).name, Path(zoom).name, '待处理'))

    def import_from_folder(self):
        """从文件夹导入并自动匹配"""
        folder = filedialog.askdirectory(title='选择图像文件夹')
        if not folder:
            return

        # 获取所有图像文件
        image_extensions = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}
        files = []
        for f in Path(folder).iterdir():
            if f.suffix.lower() in image_extensions:
                files.append(f)

        if not files:
            messagebox.showwarning("警告", "文件夹中没有找到图像文件")
            return

        # 根据匹配模式进行配对
        pattern = self.auto_match_pattern.get()
        pairs = []

        if pattern == 'suffix':
            # 倍率后缀匹配 (10x/40x, 4x/20x 等)
            low_mag = {}
            high_mag = {}
            for f in files:
                name = f.stem.lower()
                if '10x' in name or '4x' in name or '5x' in name:
                    key = re.sub(r'_?\d+x', '', name)
                    low_mag[key] = f
                elif '40x' in name or '20x' in name or '100x' in name:
                    key = re.sub(r'_?\d+x', '', name)
                    high_mag[key] = f

            for key in low_mag:
                if key in high_mag:
                    pairs.append((str(low_mag[key]), str(high_mag[key])))

        elif pattern == 'pano_zoom':
            # pano/zoom 后缀匹配
            pano_files = {}
            zoom_files = {}
            for f in files:
                name = f.stem.lower()
                if 'pano' in name or 'panorama' in name or 'overview' in name:
                    key = re.sub(r'_?(pano|panorama|overview)', '', name)
                    pano_files[key] = f
                elif 'zoom' in name or 'detail' in name or 'magnif' in name:
                    key = re.sub(r'_?(zoom|detail|magnif\w*)', '', name)
                    zoom_files[key] = f

            for key in pano_files:
                if key in zoom_files:
                    pairs.append((str(pano_files[key]), str(zoom_files[key])))

        if pairs:
            for pano, zoom in pairs:
                self.file_pairs.append((pano, zoom))
                self.tree.insert('', tk.END, values=(Path(pano).name, Path(zoom).name, '待处理'))
            messagebox.showinfo("导入完成", f"成功匹配 {len(pairs)} 对图像")
        else:
            messagebox.showwarning("匹配失败", "未能自动匹配任何图像对，请尝试手动添加")

    def remove_selected(self):
        """删除选中的文件对"""
        selected = self.tree.selection()
        for item in selected:
            idx = self.tree.index(item)
            self.tree.delete(item)
            if idx < len(self.file_pairs):
                del self.file_pairs[idx]

    def clear_list(self):
        """清空列表"""
        self.tree.delete(*self.tree.get_children())
        self.file_pairs = []

    def select_output_dir(self):
        """选择输出目录"""
        folder = filedialog.askdirectory(title='选择输出目录')
        if folder:
            self.output_dir.set(folder)

    def start_processing(self):
        """开始批量处理"""
        if not self.file_pairs:
            messagebox.showwarning("警告", "请先添加文件对")
            return

        if not self.output_dir.get():
            messagebox.showwarning("警告", "请选择输出目录")
            return

        self.processing = True
        self.start_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)

        # 在后台线程处理
        import threading
        thread = threading.Thread(target=self.process_files)
        thread.start()

    def process_files(self):
        """处理所有文件"""
        total = len(self.file_pairs)
        success = 0
        failed = 0

        ext_map = {'PNG': '.png', 'JPEG': '.jpg', 'TIFF': '.tif'}
        ext = ext_map.get(self.output_format.get(), '.png')

        for i, (pano, zoom) in enumerate(self.file_pairs):
            if not self.processing:
                break

            # 更新进度
            progress = (i / total) * 100
            self.progress_var.set(progress)
            self.progress_label.configure(text=f"处理中: {i+1}/{total}")

            # 更新树状态
            item = self.tree.get_children()[i]
            self.tree.set(item, 'status', '处理中...')
            self.dialog.update()

            try:
                # 生成输出文件名
                name = Path(pano).stem
                output_name = self.naming_pattern.get().replace('{name}', name) + ext
                output_path = Path(self.output_dir.get()) / output_name

                # 调用核心函数
                result = create_zoom_figure(
                    panorama_path=pano,
                    zoom_path=zoom,
                    output_path=str(output_path),
                    box_color=self.gui.color_var,
                    box_thickness=self.gui.box_thickness_var.get(),
                    line_color=self.gui.color_var,
                    line_thickness=self.gui.line_thickness_var.get(),
                    zoom_position=self.gui.position_var.get(),
                    padding=self.gui.padding_var.get(),
                    zoom_box_color=self.gui.color_var,
                    zoom_box_thickness=self.gui.box_thickness_var.get(),
                    line_style=self.gui.line_style_var.get(),
                    dash_length=self.gui.dash_length_var.get(),
                    gap_length=self.gui.gap_length_var.get(),
                )

                self.tree.set(item, 'status', '完成')
                success += 1

            except Exception as e:
                self.tree.set(item, 'status', f'失败: {str(e)[:20]}')
                failed += 1

        # 完成
        self.progress_var.set(100)
        self.progress_label.configure(text=f"完成: 成功 {success}, 失败 {failed}")
        self.processing = False
        self.start_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)

        if failed == 0:
            messagebox.showinfo("处理完成", f"成功处理 {success} 个文件")
        else:
            messagebox.showwarning("处理完成", f"成功: {success}, 失败: {failed}")

    def cancel_processing(self):
        """取消处理"""
        self.processing = False
        self.progress_label.configure(text="已取消")


class RatioCalculatorDialog:
    """像素/μm比例计算器对话框"""

    def __init__(self, parent, gui_instance, target):
        """
        Args:
            parent: 父窗口
            gui_instance: ROIZoomGUI实例
            target: 'pano' 或 'zoom'，指定要设置哪个比例尺的比例
        """
        self.gui = gui_instance
        self.target = target

        # 创建对话框窗口
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("像素/μm 比例计算器")
        self.dialog.geometry("400x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 变量
        self.pixel_length = tk.DoubleVar(value=100)
        self.actual_length = tk.DoubleVar(value=100)
        self.unit = tk.StringVar(value='μm')
        self.result = tk.DoubleVar(value=1.0)

        self.create_widgets()

        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """创建对话框组件"""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 说明
        info_text = "通过已知标尺计算像素/μm比例：\n" \
                    "1. 在图像软件中测量已知标尺的像素长度\n" \
                    "2. 输入标尺的实际长度和单位\n" \
                    "3. 点击计算获得比例值"
        ttk.Label(main_frame, text=info_text, justify=tk.LEFT, wraplength=350).pack(anchor=tk.W, pady=(0, 15))

        # 像素长度输入
        pixel_frame = ttk.Frame(main_frame)
        pixel_frame.pack(fill=tk.X, pady=5)
        ttk.Label(pixel_frame, text="标尺像素长度:").pack(side=tk.LEFT)
        ttk.Entry(pixel_frame, textvariable=self.pixel_length, width=12).pack(side=tk.LEFT, padx=10)
        ttk.Label(pixel_frame, text="像素").pack(side=tk.LEFT)

        # 实际长度输入
        actual_frame = ttk.Frame(main_frame)
        actual_frame.pack(fill=tk.X, pady=5)
        ttk.Label(actual_frame, text="标尺实际长度:").pack(side=tk.LEFT)
        ttk.Entry(actual_frame, textvariable=self.actual_length, width=12).pack(side=tk.LEFT, padx=10)

        # 单位选择
        unit_combo = ttk.Combobox(actual_frame, textvariable=self.unit,
                                   values=['μm', 'mm', 'nm'], width=5, state='readonly')
        unit_combo.pack(side=tk.LEFT, padx=5)

        # 计算按钮
        calc_frame = ttk.Frame(main_frame)
        calc_frame.pack(fill=tk.X, pady=15)
        ttk.Button(calc_frame, text="计算", command=self.calculate).pack(side=tk.LEFT)

        # 结果显示
        result_frame = ttk.LabelFrame(main_frame, text="计算结果", padding="10")
        result_frame.pack(fill=tk.X, pady=10)

        self.result_label = ttk.Label(result_frame, text="像素/μm = --", font=('Helvetica', 12, 'bold'))
        self.result_label.pack(anchor=tk.W)

        # 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(btn_frame, text="应用并关闭", command=self.apply_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.dialog.destroy).pack(side=tk.RIGHT)

    def calculate(self):
        """计算像素/μm比例"""
        try:
            pixel_len = self.pixel_length.get()
            actual_len = self.actual_length.get()
            unit = self.unit.get()

            if pixel_len <= 0 or actual_len <= 0:
                messagebox.showwarning("警告", "长度必须大于0")
                return

            # 转换为微米
            if unit == 'mm':
                actual_len_um = actual_len * 1000
            elif unit == 'nm':
                actual_len_um = actual_len / 1000
            else:  # μm
                actual_len_um = actual_len

            # 计算比例
            ratio = pixel_len / actual_len_um
            self.result.set(ratio)

            self.result_label.configure(text=f"像素/μm = {ratio:.4f}")

        except Exception as e:
            messagebox.showerror("错误", f"计算出错: {str(e)}")

    def apply_and_close(self):
        """应用结果并关闭"""
        ratio = self.result.get()
        if ratio <= 0:
            messagebox.showwarning("警告", "请先计算有效的比例值")
            return

        # 应用到对应的比例尺
        if self.target == 'pano':
            self.gui.pano_scale_bar_pixels_per_um.set(ratio)
        else:
            self.gui.zoom_scale_bar_pixels_per_um.set(ratio)

        self.dialog.destroy()

        # 触发预览更新
        if self.gui.debouncer:
            self.gui.debouncer.trigger()


def main():
    """主函数"""
    root = tk.Tk()

    # 设置 DPI 感知（Windows）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    # 创建应用
    app = ROIZoomGUI(root)

    # 运行主循环
    root.mainloop()


if __name__ == '__main__':
    main()
