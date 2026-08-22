#!/usr/bin/env python3
"""Generate assets/slot_timeline.drawio -- single-column (2-col paper) vertical layout."""
cells = []
def esc(s): return s
def box(i,x,y,w,h,val,fill,stroke,fc,fs=7.5,style=''):
    cells.append(f'<mxCell id="{i}" parent="1" style="rounded=1;whiteSpace=wrap;html=1;absoluteArcSize=1;arcSize=8;strokeWidth=1.2;fillColor={fill};strokeColor={stroke};fontSize={fs};fontColor={fc};{style}" value="{val}" vertex="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
def actor(i,x,y,w,h,fill,stroke):
    cells.append(f'<mxCell id="{i}" parent="1" style="shape=actor;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.2;" value="" vertex="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
def text(i,x,y,w,h,val,fc,fs=7.5,bold=1,align='left',fill='none'):
    cells.append(f'<mxCell id="{i}" parent="1" style="text;html=1;align={align};verticalAlign=middle;strokeColor=none;fillColor={fill};fontStyle={bold};fontSize={fs};fontColor={fc};" value="{val}" vertex="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
def edge(i,s,t,color,val='',ex=None,ey=None,en=None,eny=None,pts=None,dash='',ortho=True,fs=6.5,fc='#333333'):
    st=f'{"edgeStyle=orthogonalEdgeStyle;rounded=1;" if ortho else ""}html=1;endArrow=classic;endSize=5;strokeWidth=1.1;strokeColor={color};{dash}fontSize={fs};fontColor={fc};'
    if ex is not None: st+=f'exitX={ex};exitY={ey};exitDx=0;exitDy=0;'
    if en is not None: st+=f'entryX={en};entryY={eny};entryDx=0;entryDy=0;'
    p=''
    if pts: p='<Array as="points">'+''.join(f'<mxPoint x="{a}" y="{b}" />' for a,b in pts)+'</Array>'
    cells.append(f'<mxCell id="{i}" parent="1" style="{st}" value="{val}" edge="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry">{p}</mxGeometry></mxCell>')
def link(i,s,t):
    cells.append(f'<mxCell id="{i}" parent="1" style="endArrow=none;html=1;strokeColor=#9E9E9E;strokeWidth=0.8;" value="" edge="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry" /></mxCell>')

BLU=('#DAE8FC','#6C8EBF','#1F3F6C'); GRY=('#F5F5F5','#757575','#3D3D3D')
AMB=('#FFF2CC','#D6B656','#7A5C00'); PUR=('#E1D5E7','#9673A6','#5E3A70'); GRN=('#D5E8D4','#82B366','#3A6B3A')
C0=54; CW=196; W=250

# ---- chain rail (left) ----
cells.append('<mxCell id="spine" parent="1" style="endArrow=none;html=1;strokeColor=#82B366;strokeWidth=1;" edge="1"><mxGeometry relative="1" as="geometry"><mxPoint x="23" y="24" as="sourcePoint" /><mxPoint x="23" y="436" as="targetPoint" /></mxGeometry></mxCell>')
text('l-chain',0,0,46,11,'Chain',GRN[2],7.5)
text('tick0',0,14,46,9,'0 s',GRN[2],6.5,0,'center')
box('blk-p',2,26,42,24,'parent',*GRN,7)
text('tick6',0,178,46,9,'6 s',GRN[2],6.5,0,'center')
box('blk-b1',2,190,42,28,'\\(B_1\\)&lt;div&gt;&lt;font style=&quot;font-size:6px&quot;&gt;\\(PHT\\)s in &#960;&lt;/font&gt;&lt;/div&gt;',*GRN,9)
text('tick12',0,392,46,9,'12 s',GRN[2],6.5,0,'center')
box('blk-b2',2,404,42,28,'\\(B_2\\)&lt;div&gt;&lt;font style=&quot;font-size:6px&quot;&gt;\\(MT\\)s in &#960;&lt;/font&gt;&lt;/div&gt;',*GRN,9)

# ---- phase 1 ----
text('t1',C0,0,CW,12,'Step 1 &#8212; build \\(B_1\\) &#183; 0&#8211;6 s','#1A1A1A',9)
text('l-users',C0,16,80,10,'Users',BLU[2])
for k,x in enumerate((54,73,92)): actor(f'u{k}',x,28,16,22,BLU[0],BLU[1])
box('b-create',114,26,136,26,'Create \\(PHT\\) &#183; \\(c = H(m,r)\\)',*BLU)
text('l-net1',C0,58,90,10,'p2p network',GRY[2])
P=[('p1',54,72),('p2',96,68),('p3',136,80),('p4',178,68),('p5',216,78)]
for i,x,y in P: actor(i,x,y,14,20,GRY[0],GRY[1])
for k,(a,b) in enumerate([('p1','p2'),('p2','p3'),('p1','p3'),('p2','p4'),('p3','p4'),('p3','p5'),('p4','p5')]): link(f'lk{k}',a,b)
text('l-prop',C0,104,120,10,'Proposer \\(P_1\\)',AMB[2])
actor('prop',54,116,16,22,AMB[0],AMB[1])
box('b-order',76,114,110,26,'Order \\(PHT\\)s by fee&lt;div&gt;&lt;font style=&quot;font-size:6px&quot;&gt;fee metadata only&lt;/font&gt;&lt;/div&gt;',*AMB,7)
for k,y in enumerate((114,123,132)): box(f'st{k}',192,y,56,7,'',*AMB,5)
text('l-pi',192,141,56,9,'order &#960;',AMB[2],6.5,0,'center')
text('l-comm',C0,154,140,10,'Attesting committee',PUR[2])
for k,x in enumerate((54,96,138,180,222)): actor(f'att{k}',x,166,14,20,PUR[0],PUR[1])
box('b-attest',C0,190,CW,28,'Attest \\(B_1\\) &#8212; commits &#960; before any content is revealed&lt;div&gt;&lt;font style=&quot;font-size:6px&quot;&gt;BLS-aggregated&lt;/font&gt;&lt;/div&gt;',*PUR,7)

cells.append('<mxCell id="sep" parent="1" style="endArrow=none;html=1;dashed=1;dashPattern=5 5;strokeColor=#B0B0B0;strokeWidth=1;" edge="1"><mxGeometry relative="1" as="geometry"><mxPoint x="54" y="228" as="sourcePoint" /><mxPoint x="250" y="228" as="targetPoint" /></mxGeometry></mxCell>')

# ---- phase 2 ----
text('t2',C0,234,CW,12,'Step 2 &#8212; build \\(B_2\\) &#183; 6&#8211;12 s','#1A1A1A',9)
text('l-user2',C0,250,80,10,'User',BLU[2])
actor('u-rev',54,262,16,22,BLU[0],BLU[1])
cells.append(f'<mxCell id="env" parent="1" style="shape=message;whiteSpace=wrap;html=1;fillColor={BLU[0]};strokeColor={BLU[1]};strokeWidth=1.2;" value="" vertex="1"><mxGeometry x="74" y="266" width="20" height="14" as="geometry" /></mxCell>')
box('b-reveal',100,260,150,26,'Reveal \\(MT\\) &#8212; opens \\((m,r)\\)',*BLU)
text('l-net2',C0,292,90,10,'p2p network',GRY[2])
Q=[('q1',54,306),('q2',98,302),('q3',140,312),('q4',184,302)]
for i,x,y in Q: actor(i,x,y,14,20,GRY[0],GRY[1])
for k,(a,b) in enumerate([('q1','q2'),('q2','q3'),('q1','q3'),('q2','q4'),('q3','q4')]): link(f'lm{k}',a,b)
text('l-val',C0,338,150,10,'Proposers \\((n \\ge 3f{+}1)\\)',PUR[2])
for k,x in enumerate((54,96,138,180)): actor(f'v{k}',x,350,14,20,PUR[0],PUR[1])
box('b-collect',C0,374,CW,26,'Set-union on revealed \\(MT\\)s &#183; \\(f{+}1\\) threshold',*PUR)
box('b-form',C0,404,CW,28,'Build \\(B_2\\) from \\(B_1\\)&lt;div&gt;&lt;font style=&quot;font-size:6px&quot;&gt;&#960; unchanged &#183; no new vote &#183; missing \\(MT\\): burn \\(F_{res}\\)&lt;/font&gt;&lt;/div&gt;',*PUR,7)

# ---- edges ----
edge('e-bcast','b-create','p4',BLU[1],'\\(PHT\\)',0.5,1,0.5,0)
edge('e-pick','p1','prop',GRY[1],'',0.5,1,0.5,0)
edge('e-att','b-order','att1',AMB[1],'\\(B_1\\)',0.5,1,0.5,0,pts=[(131,150)])
for k in range(5):
    edge(f'ea{k}',f'att{k}','b-attest',PUR[1],'',0.5,1,round((54+42*k+7-54)/196,4),0)
edge('e-b1','b-attest','blk-b1',PUR[1],'',0,0.5,1,0.5)
edge('e-p2b1','blk-p','blk-b1',GRN[1],'',0.5,1,0.5,0)
edge('e-rev','b-reveal','q4',BLU[1],'\\(MT\\)',0.5,1,0.5,0)
edge('e-q','q1','v0',GRY[1],'',0.5,1,0.5,0)
for k in range(4):
    edge(f'ec{k}',f'v{k}','b-collect',PUR[1],'',0.5,1,round((54+42*k+7-54)/196,4),0)
edge('e-form','b-collect','b-form',PUR[1],'',0.5,1,0.5,0)
edge('e-b2','b-form','blk-b2',PUR[1],'',0,0.5,1,0.5)
edge('e-b1b2','blk-b1','blk-b2',GRN[1],'',0.5,1,0.5,0)
edge('e-fb','blk-b1','u-rev',GRN[1],'&#960; public',1,0.5,0,0.5,pts=[(48,204),(48,273)],dash='dashed=1;dashPattern=4 4;')

xml = f'''<mxfile host="app.diagrams.net" agent="Claude Code">
  <diagram name="P2S slot timeline" id="p2s-slot-timeline">
    <mxGraphModel dx="250" dy="436" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="250" pageHeight="436" math="1" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        {chr(10)+"        ".join(cells)}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
'''
open('assets/slot_timeline.drawio','w').write(xml)
print('written')
