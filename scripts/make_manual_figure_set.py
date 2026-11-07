# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT=Path(r'D:\work-projects\在役检查系统-指套管数据管理工具\01_当前软件\软件正式版_20261021')
OUT=ROOT/'tmp'/'manual-figures'; OUT.mkdir(parents=True,exist_ok=True)
FONT=r'C:\Windows\Fonts\msyh.ttc'

def ft(n):
    try: return ImageFont.truetype(FONT,n)
    except: return ImageFont.load_default()

def banner(src,name,title,subtitle=''):
    im=Image.open(src).convert('RGB')
    d=ImageDraw.Draw(im)
    h=72; canvas=Image.new('RGB',(im.width,im.height+h),'#102a43'); canvas.paste(im,(0,h)); d=ImageDraw.Draw(canvas)
    d.text((24,14),title,font=ft(28),fill='white')
    if subtitle: d.text((24,45),subtitle,font=ft(15),fill='#c9d8e8')
    canvas.save(OUT/name,quality=94)

def callouts(src,name,items,title):
    im=Image.open(src).convert('RGB'); d=ImageDraw.Draw(im)
    for i,(x,y,tx,ty,label) in enumerate(items,1):
        d.line((x,y,tx,ty),fill='#e84545',width=5)
        r=20; d.ellipse((x-r,y-r,x+r,y+r),fill='#e84545',outline='white',width=3)
        d.text((x-7,y-14),str(i),font=ft(20),fill='white')
        box=(tx+8,ty-20,tx+8+max(150,len(label)*22),ty+20)
        d.rounded_rectangle(box,radius=6,fill='#102a43',outline='white',width=2)
        d.text((tx+16,ty-12),label,font=ft(17),fill='white')
    banner_path=OUT/(name.replace('.png','_tmp.png'))
    im.save(banner_path,quality=94); banner(banner_path,name,title,'编号对应正文操作说明')
    banner_path.unlink(missing_ok=True)

banner(ROOT/'tmp'/'import-layout'/'import-progress.png','01_导入进度.png','数据导入：进度与动态反馈','等待、解析、校验、入库四个阶段')
banner(ROOT/'tmp'/'state-maintenance-1792773680557'/'failure.png','02_状态导入失败重试.png','状态导入：失败提示与重试','失败时保留原文件选择，不修改数据库')
callouts(ROOT/'tmp'/'reference-model'/'mode-plate.png','03_三维_管板视图.png',[(250,250,40,130,'管板孔位'),(650,470,820,400,'缺陷高亮'),(950,100,1050,140,'视图工具')],'三维模型：管板视图')
callouts(ROOT/'tmp'/'reference-model'/'mode-assembly.png','04_三维_整体装配.png',[(520,300,60,170,'整体结构'),(900,510,1050,470,'管束'),(1200,130,1050,170,'模型设置')],'三维模型：整体装配视图')
callouts(ROOT/'tmp'/'visualization-1792760832693'/'chart31-fullscreen.png','05_可视化_磨损趋势.png',[(350,240,40,140,'趋势曲线'),(820,140,900,100,'悬浮数据'),(1040,60,820,60,'统计说明')],'可视化：群厂磨损趋势')
callouts(ROOT/'tmp'/'visualization-1792760832693'/'chart32-fullscreen.png','06_可视化_P位趋势.png',[(350,250,40,140,'P位曲线'),(850,140,900,100,'图例'),(1000,70,760,70,'口径说明')],'可视化：P1-P5分层趋势')
callouts(ROOT/'tmp'/'visualization-1792760832693'/'plate-details.png','07_可视化_管板详情.png',[(300,260,50,150,'管板孔位'),(800,230,900,170,'单管详情'),(920,500,760,500,'状态与来源')],'可视化：管板分布与单管详情')
banner(ROOT/'tmp'/'visualization-1792760832693'/'workspace-900.png','08_可视化_小窗口.png','可视化：小窗口布局','窗口缩小时保持两列卡片和可滚动查看')
