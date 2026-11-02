"""Small offline UML sequence renderer. Source of messages is also the .mmd file."""
import re
from html import escape
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    source=(ROOT/'docs/process.mmd').read_text(encoding='utf-8')
    actors=[];messages=[];frames=[];stack=[]
    for line in source.splitlines():
        m=re.match(r'\s*(actor|participant) (\w+) as (.+)',line)
        if m:actors.append((m[2],m[3]))
        m=re.match(r'\s*(\w+)(--?>>?)(\w+): (.+)',line)
        if m:messages.append((m[1],m[3],m[4],m[2].startswith('--')))
        m=re.match(r'\s*(opt|loop) (.+)',line)
        if m:stack.append((len(messages),m[1]+' '+m[2]))
        if line.strip()=='end' and stack:
            start,label=stack.pop();frames.append((start,len(messages),label))
    width=1440;height=200+len(messages)*58
    positions={name:110+i*235 for i,(name,label) in enumerate(actors)}
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L9,4 L0,8" fill="none" stroke="#315e50"/></marker></defs>',
         f'<rect width="{width}" height="{height}" fill="#fafcfb"/>',
         '<text x="40" y="38" font-family="Arial" font-size="22" fill="#204b3d">Атлас — UML-диаграмма последовательности</text>']
    for name,label in actors:
        x=positions[name];svg.extend([f'<rect x="{x-100}" y="65" width="200" height="44" rx="4" fill="#e4eee8" stroke="#8ba698"/>',
          f'<text x="{x}" y="92" text-anchor="middle" font-family="Arial" font-size="14">{escape(label)}</text>',
          f'<line x1="{x}" y1="109" x2="{x}" y2="{height-35}" stroke="#bdcec3" stroke-dasharray="5 5"/>'])
    for start,stop,label in frames:
        involved={party for message in messages[start:stop] for party in message[:2]}
        left=min(positions[x] for x in involved)-30;right=max(positions[x] for x in involved)+30
        y=150+start*58-24;frameheight=(stop-start)*58+10
        svg.append(f'<rect x="{left}" y="{y}" width="{right-left}" height="{frameheight}" fill="#f0f6f0" fill-opacity="0.6" stroke="#afc3b4"/>')
        svg.append(f'<text x="{left+7}" y="{y+13}" font-family="Arial" font-size="10" fill="#536c5c">{escape(label)}</text>')
    for i,(a,b,label,dashed) in enumerate(messages):
        y=150+i*58;x1=positions[a];x2=positions[b];dash=' stroke-dasharray="5 4"' if dashed else ''
        if a==b:
            svg.append(f'<path d="M{x1},{y} h65 v22 h-65" fill="none" stroke="#315e50" marker-end="url(#arrow)"/>')
            tx=x1+75;ty=y+16;anchor='start'
        else:
            svg.append(f'<line x1="{x1}" y1="{y+18}" x2="{x2}" y2="{y+18}" stroke="#315e50"{dash} marker-end="url(#arrow)"/>')
            tx=(x1+x2)/2;ty=y+10;anchor='middle'
        svg.append(f'<text x="{tx}" y="{ty}" text-anchor="{anchor}" font-family="Arial" font-size="12" fill="#24483b">{i+1}. {escape(label)}</text>')
    svg.append('</svg>');(ROOT/'docs/process.svg').write_text('\n'.join(svg),encoding='utf-8')

if __name__=='__main__':main()
