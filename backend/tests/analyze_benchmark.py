# Benchmark image structural visual analysis
from PIL import Image, ImageFilter
import numpy as np

def analyze(path, label):
    img = Image.open(path).convert('RGB')
    arr = np.array(img, dtype=np.float64)
    h, w = arr.shape[:2]
    gray = img.convert('L')
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.array(edges, dtype=np.float64)
    tex = gray.filter(ImageFilter.Kernel((3,3), [-1,-1,-1,-1,8,-1,-1,-1,-1], scale=1))
    tex_arr = np.array(tex, dtype=np.float64)
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    lum_arr = 0.299*r + 0.587*g + 0.114*b

    print('=' * 55)
    print(f'  {label} ({w}x{h})')
    print('=' * 55)

    # 1. Grid color
    print('\n--- Grid Color (R G B L [nature/temp]) ---')
    thirds_h = [0, h//3, 2*h//3, h]
    thirds_w = [0, w//3, 2*w//3, w]
    rows = ['Top', 'Mid', 'Bot']
    cols = ['L  ', 'C  ', 'R  ']
    for ri in range(3):
        for ci in range(3):
            reg = arr[thirds_h[ri]:thirds_h[ri+1], thirds_w[ci]:thirds_w[ci+1]]
            rm, gm, bm = reg[:,:,0].mean(), reg[:,:,1].mean(), reg[:,:,2].mean()
            lum = 0.299*rm + 0.587*gm + 0.114*bm
            n = 'SHAD' if lum<70 else ('MID ' if lum<150 else 'HIGH')
            t = 'W' if rm>bm*1.08 else ('C' if bm>rm*1.08 else 'N')
            print(f'  {rows[ri]}-{cols[ci]}: R{rm:4.0f} G{gm:4.0f} B{bm:4.0f} L{lum:4.0f} [{n}/{t}]')

    # 2. Edge density (composition complexity)
    et, em, eb = edge_arr[:h//3,:].mean(), edge_arr[h//3:2*h//3,:].mean(), edge_arr[2*h//3:,:].mean()
    el, ec, er = edge_arr[:,:w//3].mean(), edge_arr[:,w//3:2*w//3].mean(), edge_arr[:,2*w//3:].mean()
    print(f'\n--- Edge Density ---')
    print(f'  Total={edge_arr.mean():.0f}  V: T={et:.0f} M={em:.0f} B={eb:.0f}  H: L={el:.0f} C={ec:.0f} R={er:.0f}')
    # Where is the most detail?
    v_peak = 'top' if et>em and et>eb else ('mid' if em>eb else 'bot')
    h_peak = 'left' if el>ec and el>er else ('center' if ec>er else 'right')
    print(f'  Detail peak: V={v_peak} H={h_peak}')

    # 3. Texture / depth
    tt, tb = np.abs(tex_arr[:h//3,:]).mean(), np.abs(tex_arr[2*h//3:,:]).mean()
    t_ratio = tb / max(tt, 1)
    print(f'\n--- Texture ---')
    print(f'  Mean={np.abs(tex_arr).mean():.1f}  Top={tt:.1f}  Bot={tb:.1f}  Bot/Top={t_ratio:.2f}')
    if t_ratio > 1.2:
        print(f'  => Depth: detailed foreground + smoother background')
    elif t_ratio < 0.85:
        print(f'  => Reverse depth: top more detailed than bottom')
    else:
        print(f'  => Flat/shallow depth')

    # 4. Human detection
    skin = ((r>95)&(g>40)&(b>20)&(r>g)&(r>b)&
            ((np.maximum(np.maximum(r,g),b)-np.minimum(np.minimum(r,g),b))>15))
    skin_top = skin[:h//3, :].mean()
    skin_mid = skin[h//3:2*h//3, :].mean()
    skin_bot = skin[2*h//3:, :].mean()
    print(f'\n--- Human Presence (skin tone detection) ---')
    print(f'  Total={skin.mean():.1%}  Top={skin_top:.1%}  Mid={skin_mid:.1%}  Bot={skin_bot:.1%}')
    if skin_mid > 0.05:
        print(f'  => Human figures present (mid-frame skin > 5%)')
    else:
        print(f'  => Minimal or no human figures')

    # 5. Composition center
    y_w = np.arange(h)[:, None]
    x_w = np.arange(w)[None, :]
    total_l = lum_arr.sum()
    cy = (y_w*lum_arr).sum()/total_l/h
    cx = (x_w*lum_arr).sum()/total_l/w
    focus_w = lum_arr * np.abs(tex_arr)
    total_f = focus_w.sum()
    fy = (y_w*focus_w).sum()/total_f/h
    fx = (x_w*focus_w).sum()/total_f/w
    print(f'\n--- Composition Center ---')
    print(f'  Luminance center:  y={cy:.2f} x={cx:.2f}')
    print(f'  Focus center:      y={fy:.2f} x={fx:.2f}')
    yp = 'upper-third' if fy<0.38 else ('middle' if fy<0.62 else 'lower-third')
    xp = 'left' if fx<0.38 else ('center' if fx<0.62 else 'right')
    rule_of_thirds = 'yes (off-center)' if abs(fy-0.5)>0.1 or abs(fx-0.5)>0.1 else 'no (dead center)'
    print(f'  Subject placement: {yp} {xp} | Rule-of-thirds: {rule_of_thirds}')

    # 6. Spatial depth cues
    sky_r, sky_b = arr[:h//3, :, 0].mean(), arr[:h//3, :, 2].mean()
    gnd_r, gnd_b = arr[2*h//3:, :, 0].mean(), arr[2*h//3:, :, 2].mean()
    top_lum = lum_arr[:h//3,:].mean()
    bot_lum = lum_arr[2*h//3:,:].mean()
    print(f'\n--- Spatial Depth ---')
    print(f'  Sky area:  L={top_lum:.0f} R/B={sky_r/max(sky_b,1):.2f}')
    print(f'  Ground:    L={bot_lum:.0f} R/B={gnd_r/max(gnd_b,1):.2f}')
    if top_lum>bot_lum*1.15 and tt<tb*0.9:
        print(f'  => Classic depth: bright sky/ceiling + detailed ground')
    elif bot_lum>top_lum*1.15:
        print(f'  => Indoor/reverse: foreground lit, background shadow')
    else:
        print(f'  => Compressed space / shallow depth of field')

    # 7. Warm/cool by zone
    warm = r > b*1.05
    cool = b > r*1.05
    print(f'\n--- Color Temp by Zone ---')
    print(f'  Top:    warm={warm[:h//3,:].mean():.1%}  cool={cool[:h//3,:].mean():.1%}')
    print(f'  Middle: warm={warm[h//3:2*h//3,:].mean():.1%}  cool={cool[h//3:2*h//3,:].mean():.1%}')
    print(f'  Bottom: warm={warm[2*h//3:,:].mean():.1%}  cool={cool[2*h//3:,:].mean():.1%}')

    print()


# Run for benchmark images
for i in [1,2,3]:
    analyze(f'C:/Users/Admin/Desktop/对标{i}.png', f'标杆{i}')

# Also analyze our old and new versions for comparison
for label, paths in [
    ('chinese_docu_v1', ['D:/chinese_docu_test/test_01.png', 'D:/chinese_docu_test/test_02.png', 'D:/chinese_docu_test/test_03.png']),
    ('gemini_v2', ['D:/gemini_style_test/gemini_01.png', 'D:/gemini_style_test/gemini_02.png', 'D:/gemini_style_test/gemini_03.png']),
]:
    for idx, path in enumerate(paths):
        analyze(path, f'{label}_{idx+1}')
