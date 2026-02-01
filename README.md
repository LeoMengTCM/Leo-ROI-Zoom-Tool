# Leo ROI Zoom Tool

科研图像局部放大图制作工具

**作者**: Leo Meng (Linghan Meng)
**版本**: 2.0

## 功能特性

- **自动ROI识别**: 使用模板匹配自动定位放大区域在全景图中的位置
- **多方向拼接**: 支持上/下/左/右四个方向放置放大图
- **比例尺**: 支持为全景图和放大图分别添加比例尺，可自定义样式、位置、字体
- **标注工具**: 箭头、星号、圆形、三角形、文字标注
- **水印**: 可添加自定义水印文字
- **批量处理**: 支持批量处理多组图像
- **实时预览**: 参数调整后自动预览（防抖）
- **快捷键**: Ctrl/Cmd+G生成、Ctrl/Cmd+S保存、Ctrl/Cmd+Z撤销

## 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install opencv-python numpy pillow
```

## 使用方法

```bash
python roi_zoom_gui.py
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl/Cmd + G | 生成预览 |
| Ctrl/Cmd + S | 保存图像 |
| Ctrl/Cmd + Z | 撤销 |
| Ctrl/Cmd + Shift + Z | 重做 |
| Ctrl/Cmd + R | 重置ROI位置 |
| Escape | 取消当前操作 |

## 比例尺像素/μm计算

点击"计算"按钮，输入已知标尺的像素长度和实际长度即可自动计算比例。

## 文件说明

- `roi_zoom_gui.py` - 图形界面主程序
- `roi_zoom_tool_v2.py` - 核心处理模块
- `.roi_zoom_config.json` - 配置文件（自动生成）

## 许可证

MIT License
