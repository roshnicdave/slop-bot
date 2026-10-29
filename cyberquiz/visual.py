"""Reference-inspired visual quizzes. Diagrams carry the problem, not decoration."""
import copy
import json
import math
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

from PIL import Image,ImageDraw
from .render import font,wrap,duration

W,H=720,1280
NAVY='#112f50';INK='#102b45';BLUE='#dceefa';TEAL='#087f82';GREEN='#15804a';RED='#cb4248'
F= lru_cache(maxsize=100)(font)


def text(d,s,x,y,size=25,color=INK,bold=False,width=None,center=False):
    f=F(size,bold);lines=wrap(s,f,width) if width else s.split('\n')
    for line in lines:
        px=x-f.getlength(line)/2 if center else x
        d.text((px,y),line,font=f,fill=color)
        y+=size+7
    return y


def pill(d,label,x,y,color=TEAL,fill='#edf8f8',width=None):
    f=F(18,True);w=width or int(f.getlength(label))+28
    d.rounded_rectangle((x-w/2,y,x+w/2,y+34),radius=10,fill=fill)
    text(d,label,x,y+6,18,color,True,center=True)


def pc(d,x,y):
    d.rounded_rectangle((x-42,y-35,x+42,y+25),radius=7,fill='#e4f0f8',outline=NAVY,width=3)
    d.rounded_rectangle((x-34,y-27,x+34,y+16),radius=3,fill='#b9dceb')
    d.line((x,y+25,x,y+38),fill=NAVY,width=5)
    d.rounded_rectangle((x-29,y+36,x+29,y+43),radius=3,fill=NAVY)


def device(d,x,y,kind='switch'):
    d.rounded_rectangle((x-58,y-28,x+58,y+31),radius=10,fill='#30778b',outline=NAVY,width=2)
    for n in range(5):
        d.rectangle((x-42+n*19,y+13,x-31+n*19,y+22),fill='#daedf3')
    if kind=='router':
        d.line((x-30,y-8,x+30,y-8),fill='white',width=3)
        d.line((x,y-22,x,y+6),fill='white',width=3)
    else:
        d.line((x-30,y-12,x+26,y-12),fill='white',width=3)
        d.polygon([(x+26,y-18),(x+37,y-12),(x+26,y-6)],fill='white')
        d.line((x+30,y-2,x-26,y-2),fill='white',width=3)
        d.polygon([(x-26,y-8),(x-37,y-2),(x-26,y+4)],fill='white')


def cloud(d,x,y):
    for box in [(x-48,y-7,x+48,y+37),(x-35,y-34,x+20,y+25),(x-1,y-22,x+46,y+30)]:
        d.ellipse(box,fill='#d6eaf6',outline=None)
    text(d,'WAN',x,y,20,NAVY,True,center=True)


def topology(d,p,fixed=False,phase=0):
    scene=copy.deepcopy(p['diagram']);fix=p.get('fix_diagram',{})
    if fixed:
        if 'right_vlan' in fix:scene['right']['vlan']=fix['right_vlan']
        if 'right_ip' in fix:scene['right']['ip']=fix['right_ip']
        if 'left_gateway' in fix:scene['left']['gateway']=fix['left_gateway']
        if fix.get('dns_reachable'):scene['right']['ip']='DNS query: REPLY'
    if scene['kind']=='config':
        d.rounded_rectangle((26,356,694,637),radius=22,fill='#102b45')
        model=p.get('model',{});kind=model.get('kind');lines=list(scene['lines']);highlight=None;color=GREEN
        if p.get('_reveal') or fixed:
            if kind=='route':highlight=next((i+1 for i,(_,hop) in enumerate(model['routes']) if hop==p['answer']),None)
            elif kind in ('acl','trunk','mtu','broadcast','tls','duplicate'):highlight={'acl':1,'trunk':2,'mtu':0,'broadcast':0,'tls':1,'duplicate':1}[kind];color=GREEN if fixed else RED
        repaired=fixed and kind in ('acl','trunk','mtu','broadcast','tls','duplicate')
        if repaired:
            if kind=='acl':
                for i,(action,net) in enumerate(model['fixed_rules']):lines[i+1]=f'{10*(i+1)} {action} {net}'
            elif kind=='trunk':lines[2]='Switch B trunk allows: '+','.join(map(str,model['fixed_b']))
            elif kind=='mtu':lines[0]=f'IP packet: {model["fixed_packet"]} bytes, DF = 1'
            elif kind=='broadcast':lines[0]='PC: '+model['fixed']
            elif kind=='tls':lines[1]='Certificate SAN: '+model['host']
            elif kind=='duplicate':lines[1]='PC B: '+model['fixed_b']+', MAC ...:BB';lines[2]='Conflict removed. Update ARP if needed.'
        label='FIXED CONFIG' if repaired else 'FORWARDING DECISION' if fixed and kind=='route' else 'ORIGINAL EVIDENCE' if fixed else 'EVIDENCE / CONFIG'
        text(d,label,48,375,17,'#8dc9d4',True)
        for i,line in enumerate(lines):
            size=25;yy=419+i*46
            if i==highlight:d.rounded_rectangle((39,yy-5,681,yy+35),radius=6,fill='#173f3a' if color==GREEN else '#512f38',outline=color,width=2)
            while F(size,True).getlength(line)>620:size-=1
            text(d,line,48,yy,size,'#ffffff',True)
        return
    x1,x2,x3=115,360,605;y=470
    d.rounded_rectangle((26,356,694,637),radius=22,fill='white',outline='#dae5ee',width=2)
    # Two distinct link segments. Their green lights are explicit evidence.
    d.line((x1+44,y,x2-58,y),fill='#3c586a',width=4)
    d.line((x2+58,y,x3-46,y),fill='#3c586a',width=4)
    for x in [x1+50,x2-65,x2+65,x3-53]:d.rectangle((x-4,y-4,x+4,y+4),fill='#40a96d')
    pc(d,x1,y)
    kind=scene['kind']
    device(d,x2,y,'router' if kind=='router' else 'switch')
    if kind=='router':cloud(d,x3,y)
    elif kind=='dns':
        d.rounded_rectangle((x3-32,y-44,x3+32,y+41),radius=7,fill='#d9e9f4',outline=NAVY,width=3)
        for yy in [y-29,y-7,y+15]:d.line((x3-19,yy,x3+19,yy),fill=NAVY,width=3)
    else:pc(d,x3,y)
    for x,node in [(x1,scene['left']),(x3,scene['right'])]:
        if 'vlan' in node:
            same=fixed or scene['left'].get('vlan')==scene['right'].get('vlan')
            pill(d,'VLAN '+str(node['vlan']),x,382,TEAL if same or x==x1 else '#a05822',
                 '#e6f5f3' if same or x==x1 else '#fff0e3')
        text(d,node['name'],x,529,22,INK,True,center=True)
        # Addresses stay outside icon silhouettes and link paths.
        ip=node.get('ip','');text(d,ip,x,562,16,'#52687b',center=True)
        if node.get('gateway'):
            text(d,'GW '+node['gateway'],x,594,15,GREEN if fixed else RED,True,center=True)
    text(d,'ROUTER' if kind=='router' else 'L2 SWITCH',x2,526,16,'#52687b',True,center=True)
    if not scene.get('routing'):text(d,'no routing',x2,551,15,'#52687b',center=True)
    # A moving packet shows where delivery stops; the fix lets it cross.
    progress=phase%1
    end=x3-50 if fixed else x2-70
    px=(x1+54)+(end-(x1+54))*progress
    d.rounded_rectangle((px-9,y-7,px+9,y+7),radius=3,fill=GREEN if fixed else '#3688d1',outline='white',width=1)
    if not fixed and p.get('_reveal'):
        d.ellipse((x2-92,y-15,x2-62,y+15),fill=RED)
        text(d,'x',x2-77,y-15,22,'white',True,center=True)
    if fixed:pill(d,'PING OK' if kind not in ['dns'] else 'DNS OK',x2,590,GREEN,'#e1f4e8')


def frame(p,stage='question',remaining=None,phase=0,progress=0,subtitle=None):
    im=Image.new('RGB',(W,H),'#f7fafc');d=ImageDraw.Draw(im)
    text(d,'@'+p.get('account','network.quiz'),34,43,19,'#536b7d',True)
    text(d,'SPOT THE FAULT',686,43,16,TEAL,True,center=False) if False else None
    pill(d,'NETWORK CHALLENGE',571,39,TEAL,'#e6f4f4',228)
    d.rounded_rectangle((26,94,694,282),radius=28,fill=NAVY)
    lines=p['question'].split('\n')
    for i,line in enumerate(lines):
        size=45
        while F(size,True).getlength(line)>620:size-=1
        text(d,line,360,128+i*59,size,'white',True,center=True)
    text(d,p['clue'],360,312,16,'#506579',width=650,center=True)
    view=copy.deepcopy(p);view['_reveal']=stage=='reveal'
    topology(d,view,stage=='fix',phase)
    if stage=='fix':
        text(d,p['fix_label'],360,706,36,GREEN,True,width=625,center=True)
        text(d,p['fix'],360,785,29,INK,width=610,center=True)
        text(d,p.get('closing_prompt','Which clue gave it away?'),360,917,23,'#52687b',width=610,center=True)
    else:
        for i,option in enumerate(p['options']):
            yy=665+i*88;right=stage=='reveal' and i==p['correct']
            d.rounded_rectangle((29,yy+4,691,yy+77),radius=16,fill='#e0e7ed')
            d.rounded_rectangle((27,yy,693,yy+73),radius=16,fill='#e0f3e6' if right else BLUE,
                                outline=GREEN if right else '#cbdfe9',width=3 if right else 1)
            text(d,'ABCD'[i]+'.',55,yy+17,30,GREEN if right else INK,True)
            size=30
            while F(size,True).getlength(option)>545:size-=1
            text(d,option,112,yy+18,size,GREEN if right else INK,True)
        if stage=='reveal':
            text(d,p['explanation'],360,1047,25,INK,width=640,center=True)
        else:
            d.rounded_rectangle((32,1058,688,1066),radius=4,fill='#d7e3eb')
            d.rounded_rectangle((32,1058,32+max(1,int(656*(1-progress))),1066),radius=4,fill=TEAL)
            if subtitle:text(d,subtitle,360,1080,22,'#476176',width=640,center=True)
            else:text(d,'Which clue gives it away?',34,1093,21,'#476176',True)
            if remaining is not None:pill(d,str(remaining)+' SEC',628,1089,TEAL,'#e2f2f2',112)
    # Keep the bottom ~100 px free of required information for Instagram UI.
    text(d,p['source_label'],34,1182,13,'#697d8e')
    return im


def preview(plan,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for stage in ['question','reveal','fix']:
        frame(plan,stage,5 if stage=='question' else None,0.6).save(folder/(stage+'-preview.jpg'),quality=95)
    frame(plan).save(folder/'preview.jpg',quality=95)


def render(folder):
    folder=Path(folder).resolve();p=json.loads((folder/'plan.json').read_text());preview(p,folder)
    intro=duration(folder/'intro.wav');decision=p.get('decision_seconds',5)
    if p.get('voice_version')==2:
        reveal_audio=folder/'reveal_voice.wav';fix_audio=folder/'fix_voice.wav'
        reveal_duration=duration(reveal_audio);fix_duration=duration(fix_audio)
        fix_delay=reveal_duration;total=intro+decision+reveal_duration+fix_duration+.6
        segments=[{'stage':'question','start':0,'end':intro,'text':p['intro']},
          {'stage':'decision','start':intro,'end':intro+decision,'text':'Which clue gives it away?'},
          {'stage':'reveal','start':intro+decision,'end':intro+decision+reveal_duration,'text':p['reveal_voice']},
          {'stage':'fix','start':intro+decision+reveal_duration,'end':total-.6,'text':p['fix_voice']}]
    else:
        reveal_audio=folder/'outro.wav';fix_audio=None
        outro=duration(reveal_audio);fix_delay=min(4.4,outro*.55);total=intro+decision+outro+.6
        segments=[]
    frames=folder/'frames';frames.mkdir(exist_ok=True)
    sequence=[];fps=8;n=math.ceil(total*fps)
    # A bounded 8 fps scene animation encoded at 24 fps: no AI-video spend.
    for index in range(n):
        t=index/fps
        if t<intro+decision:
            stage='question';remain=max(1,math.ceil(intro+decision-t));progress=max(0,(t-intro)/decision)
        elif t<intro+decision+fix_delay:stage='reveal';remain=None;progress=1
        else:stage='fix';remain=None;progress=1
        im=frame(p,stage,remain if t>=intro else None,(t*.65)%1,progress, p['intro'] if t<intro else None)
        name=f'frames/{index:04d}.jpg';im.save(folder/name,quality=88)
        sequence.append(f"file '{name}'\nduration {1/fps:.4f}\n")
    concat=folder/'visual.ffconcat';concat.write_text('ffconcat version 1.0\n'+''.join(sequence)+f"file 'frames/{n-1:04d}.jpg'\n")
    with wave.open(str(folder/'intro.wav')) as a,wave.open(str(reveal_audio)) as b:
        if a.getparams()[:3]!=b.getparams()[:3]:raise ValueError('Voice sample formats differ')
        channels,width,rate=a.getparams()[:3]
        with wave.open(str(folder/'speech.wav'),'wb') as out:
            out.setnchannels(channels);out.setsampwidth(width);out.setframerate(rate)
            out.writeframes(a.readframes(a.getnframes()));out.writeframes(bytes(decision*rate*channels*width))
            out.writeframes(b.readframes(b.getnframes()))
            if fix_audio:
                with wave.open(str(fix_audio)) as c:
                    if c.getparams()[:3]!=(channels,width,rate):raise ValueError('Fix voice format differs')
                    out.writeframes(c.readframes(c.getnframes()))
            out.writeframes(bytes(int(.6*rate)*channels*width))
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-threads','1','-i',str(folder/'speech.wav'),
        '-af','loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-ac','2','-c:a','aac','-b:a','128k',str(folder/'speech.m4a')],check=True)
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-threads','1',
        '-i',str(concat),'-i',str(folder/'speech.m4a'),'-map','0:v:0','-map','1:a:0','-filter_threads','1',
        '-vf','fps=30,format=yuv420p','-c:v','libx264','-threads','1','-preset','veryfast','-tune','zerolatency',
        '-x264-params','rc-lookahead=0:ref=1:bframes=0','-crf','20','-c:a','copy','-movflags','+faststart',
        '-t',str(total),str(folder/'reel.tmp.mp4')],check=True)
    (folder/'reel.tmp.mp4').replace(folder/'reel.mp4')
    (folder/'timing.json').write_text(json.dumps({'total_seconds':total,'reveal_at':intro+decision,'fix_at':intro+decision+fix_delay,
       'narration_characters':len(p['intro'])+len(p['outro']),'animation_fps':fps,'segments':segments},indent=2))
    def timestamp(value):
        ms=round(value*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);sec,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{sec:02},{ms:03}'
    (folder/'subtitles.srt').write_text('\n\n'.join(str(i+1)+'\n'+timestamp(s['start'])+' --> '+timestamp(s['end'])+'\n'+s['text'] for i,s in enumerate(segments)))
    (folder/'caption.txt').write_text(p['caption'])
    return folder/'reel.mp4'
