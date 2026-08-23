#!/usr/bin/env python3
"""Generate assets/slot_timeline.drawio.

P2S slot as a sequence diagram: five lifelines (User / p2p network / Proposer /
Attesting committee / Chain), time flowing downward, messages as labelled
horizontal arrows. Sized for ONE column of a two-column paper (250 x 342 units
~= 3.4 x 4.7 in at 1:1, so type is not shrunk on import).

Phase timings follow README.md:56 -- "B1 / B2 phase | 6 s each" (that table calls the steps B1/B2).
Notation (S1/S2 = the two STEPS of one 12 s slot; PHT, MT, pi, F_res) follows real/SIM_SPEC.md and README.md.
"""

BLU = ('#DAE8FC', '#6C8EBF', '#1F3F6C')
GRY = ('#F5F5F5', '#757575', '#3D3D3D')
AMB = ('#FFF2CC', '#D6B656', '#7A5C00')
PUR = ('#E1D5E7', '#9673A6', '#5E3A70')
GRN = ('#D5E8D4', '#82B366', '#3A6B3A')

W, H = 250, 342
GUT = 16                                   # left gutter for time ticks
LX = dict(user=38, p2p=84, p1=130, comm=176, chain=224)
HEAD_W, HEAD_H = 44, 24
SELF_W = 52                                # self-action box width
TOP, BOT = 24, 334                         # lifeline span

cells = []


def esc(v):
    """Escape label markup for an XML attribute (entities such as &quot; pass through)."""
    return v.replace('<', '&lt;').replace('>', '&gt;')


def box(i, x, y, w, h, val, pal, fs=6.5, arc=6):
    f, s, c = pal
    cells.append(
        f'<mxCell id="{i}" parent="1" style="rounded=1;whiteSpace=wrap;html=1;'
        f'absoluteArcSize=1;arcSize={arc};strokeWidth=1.1;fillColor={f};strokeColor={s};'
        f'fontSize={fs};fontColor={c};" value="{esc(val)}" vertex="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


def selfbox(i, lane, y, val, pal, h=16):
    box(i, LX[lane] - SELF_W // 2, y, SELF_W, h, val, pal)


def band(i, a, b, y, val, pal, h=16):
    x0, x1 = LX[a] - SELF_W // 2, LX[b] + SELF_W // 2
    box(i, x0, y, x1 - x0, h, val, pal)
    return x0, x1


def text(i, x, y, w, h, val, colour, fs=6, bold=0, align='center'):
    cells.append(
        f'<mxCell id="{i}" parent="1" style="text;html=1;align={align};verticalAlign=middle;'
        f'strokeColor=none;fillColor=none;fontStyle={bold};fontSize={fs};fontColor={colour};"'
        f' value="{esc(val)}" vertex="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


def line(i, x1, y1, x2, y2, colour, w=1, dash='', arrow='none', fs=5.5, val='', fc='#333333'):
    cells.append(
        f'<mxCell id="{i}" parent="1" style="html=1;endArrow={arrow};endSize=4;'
        f'strokeWidth={w};strokeColor={colour};{dash}fontSize={fs};fontColor={fc};'
        f'verticalAlign=bottom;labelBackgroundColor=#FFFFFF;" value="{esc(val)}" edge="1">'
        f'<mxGeometry relative="1" as="geometry">'
        f'<mxPoint x="{x1}" y="{y1}" as="sourcePoint" />'
        f'<mxPoint x="{x2}" y="{y2}" as="targetPoint" /></mxGeometry></mxCell>')


def msg(i, a, b, y, val, pal, dash=''):
    """Horizontal message between two lifelines (or explicit x coords)."""
    x1 = LX[a] if isinstance(a, str) else a
    x2 = LX[b] if isinstance(b, str) else b
    line(i, x1, y, x2, y, pal[1], 1.1, dash, 'classic', 5.5, val, pal[2])


# ---------------------------------------------------------------- lifeline heads
HEADS = [('user', 'User', BLU), ('p2p', 'p2p network', GRY),
         ('p1', 'Proposer \\(P_1\\)', AMB), ('comm', 'Attesting<br>committee', PUR),
         ('chain', 'Chain', GRN)]
for lane, label, pal in HEADS:
    x = LX[lane] - HEAD_W // 2
    if lane == 'p2p':                       # network head carries a tiny peer mesh
        box(f'h-{lane}', x, 0, HEAD_W, HEAD_H, '', pal, 6, 4)
        text(f'hl-{lane}', x, 1, HEAD_W, 9, label, pal[2], 6, 1)
        dots = {'n1': (67, 13), 'n2': (79, 12), 'n3': (72, 18), 'n4': (90, 15)}
        for n, (dx, dy) in dots.items():
            cells.append(
                f'<mxCell id="{n}" parent="1" style="ellipse;html=1;fillColor={pal[1]};'
                f'strokeColor={pal[1]};" value="" vertex="1">'
                f'<mxGeometry x="{dx}" y="{dy}" width="3.5" height="3.5" as="geometry" /></mxCell>')
        for k, (p, q) in enumerate([('n1', 'n2'), ('n1', 'n3'), ('n2', 'n3'),
                                    ('n2', 'n4'), ('n3', 'n4')]):
            cells.append(
                f'<mxCell id="ml{k}" parent="1" style="endArrow=none;html=1;'
                f'strokeColor={pal[1]};strokeWidth=0.6;" value="" edge="1" '
                f'source="{p}" target="{q}"><mxGeometry relative="1" as="geometry" /></mxCell>')
    else:
        box(f'h-{lane}', x, 0, HEAD_W, HEAD_H, label, pal, 6.5, 4)

# ---------------------------------------------------------------- lifelines
for lane, _, pal in HEADS:
    solid = lane == 'chain'
    line(f'll-{lane}', LX[lane], TOP, LX[lane], BOT, pal[1],
         1 if solid else 0.9, '' if solid else 'dashed=1;dashPattern=3 3;')

# ---------------------------------------------------------------- time rules
for i, (y, lab) in enumerate([(32, '0 s'), (192, '6 s'), (334, '12 s')]):
    line(f'r{i}', GUT, y, W, y, '#C8C8C8', 0.9, 'dashed=1;dashPattern=6 4;')
    text(f'tk{i}', 0, y - 5, GUT - 2, 10, lab, '#3D3D3D', 6, 1, 'right')

# ---------------------------------------------------------------- step 1: build S1
box('blk-parent', LX['chain'] - HEAD_W // 2, 38, HEAD_W, 16, 'parent', GRN, 6.5)
selfbox('a-create', 'user', 40, 'create \\(PHT\\)', BLU)
msg('m1', 'user', 'p2p', 66, '\\(PHT\\)', BLU)
msg('m2', 'p2p', 'p1', 80, '\\(PHT\\)', GRY)
selfbox('a-order', 'p1', 88, 'order by fee', AMB)
msg('m3', 'p1', 'comm', 116, '\\(S_1(\\pi)\\)', AMB)
selfbox('a-attest', 'comm', 124, 'attest \\(S_1\\)', PUR)
msg('m4', 'comm', 'chain', 152, '\\(S_1\\)', PUR)
box('blk-s1', LX['chain'] - HEAD_W // 2, 158, HEAD_W, 20, '\\(S_1\\)'
    '<div><font style=&quot;font-size:5.5px&quot;>\\(PHT\\)s</font></div>', GRN, 8)
msg('m5', 'chain', 'user', 184,
    '\\(S_1\\) confirmed &#183; \\(\\pi\\) public', GRN, 'dashed=1;dashPattern=4 4;')

# ---------------------------------------------------------------- step 2: build S2
selfbox('a-reveal', 'user', 200, 'reveal \\(MT\\)', BLU)
msg('m6', 'user', 'p2p', 226, '\\(MT\\)', BLU)
msg('m7', 'p2p', 'p1', 240, '\\(MT\\)', GRY)
band('a-union', 'p1', 'comm', 248, 'set-union \\((f{+}1)\\)', PUR)
x0, x1 = band('a-build', 'p1', 'comm', 274, 'build \\(S_2\\) from \\(S_1\\)', PUR)
msg('m8', x1, 'chain', 300, '\\(S_2\\)', PUR)
box('blk-s2', LX['chain'] - HEAD_W // 2, 306, HEAD_W, 20, '\\(S_2\\)'
    '<div><font style=&quot;font-size:5.5px&quot;>\\(MT\\)s</font></div>', GRN, 8)

xml = ('<mxfile host="app.diagrams.net" agent="Claude Code">\n'
       '  <diagram name="P2S slot timeline" id="p2s-slot-timeline">\n'
       f'    <mxGraphModel dx="{W}" dy="{H}" grid="0" gridSize="10" guides="1" tooltips="1"'
       ' connect="1" arrows="1" fold="1" page="1" pageScale="1"'
       f' pageWidth="{W}" pageHeight="{H}" math="1" shadow="0">\n'
       '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n        '
       + '\n        '.join(cells) +
       '\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n')
open('assets/slot_timeline.drawio', 'w').write(xml)
print('written', W, 'x', H)
