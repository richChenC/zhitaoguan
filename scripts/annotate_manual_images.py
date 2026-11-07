# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT=Path(r'D:\work-projects\在役检查系统-指套管数据管理工具\01_当前软件\软件正式版_20261021')
OUT=ROOT/'tmp'/'manual-annotated'
OUT.mkdir(parents=True,exist_ok=True)
FONT_PATH=r'C:\Windows\Fonts\msyh.ttc'
def font(size):
    try: return ImageFont.truetype(FONT_PATH,size)
    except: return ImageFont.load_default()
def annotate(src,dst,items):
    im=Image.open(src).convert('RGB'); d=ImageDraw.Draw(im)
    for n,(x,y,tx,ty,label) in enumerate(items,1):
        r=18; d.ellipse((x-r,y-r,x+r,y+r),fill='#e84545',outline='white',width=3)
        d.text((x-6,y-12),str(n),font=font(18),fill='white')
        d.line((x,y,tx,ty),fill='#e84545',width=4)
        bx=tx+8; by=ty-18; tw=d.textbbox((0,0),label,font=font(18))[2]
        d.rounded_rectangle((bx,by,bx+tw+18,by+34),radius=6,fill='#102a43',outline='white',width=2)
        d.text((bx+9,by+5),label,font=font(18),fill='white')
    im.save(dst,quality=95)
annotate(ROOT/'tmp'/'visualization-1792773681518'/'overview.png',OUT/'可视化总览_标注.png',[(95,95,225,95,'基地范围筛选'),(410,95,585,95,'机组与大修筛选'),(430,280,500,280,'关键指标卡'),(370,410,220,410,'机组检查概览'),(1100,410,1300,410,'P位构成'),(500,785,700,785,'通道磨损次数分布')])
annotate(ROOT/'tmp'/'reference-model'/'reference-1894x1014.png',OUT/'三维模型_标注.png',[(88,96,220,96,'模型视图切换'),(950,150,1200,150,'检测记录筛选'),(1690,90,1580,90,'模型设置'),(80,875,200,875,'三维方向标'),(950,920,1100,920,'视角与管号'),(1520,230,1300,230,'选中管子信息')])
annotate(ROOT/'tmp'/'state-maintenance-1792768062444'/'import-1480.png',OUT/'状态导入预览_标注.png',[(410,145,240,145,'识别结果摘要'),(1130,145,900,145,'批量确认策略'),(200,365,80,365,'勾选记录'),(500,365,420,365,'状态字段'),(800,365,650,365,'位移量'),(900,430,700,430,'备注原文'),(1120,365,1060,365,'来源列'),(1200,780,1050,780,'确认导入')])
