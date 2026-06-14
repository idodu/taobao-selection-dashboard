# Fluid Commerce Command

## Style Prompt

深色流体数据空间，服务于淘宝家清个护与日化纸品选品决策。界面像一个持续接收市场信号的商品数据终端：深黑青背景、冷白信息、电光青状态、少量紫色数据光迹。强动画只用于进入、换新、筛选和翻页；阅读期间保持稳定，仅留下缓慢光迹与状态脉冲。

## Colors

- Canvas: `#071014`
- Panel: `#0D181E`
- Primary text: `#F2F7F5`
- Secondary text: `#92A4AB`
- Electric cyan: `#20D9D2`
- Data violet: `#7968FF`
- Warning amber: `#F4A340`
- Risk red: `#FF5B68`

## Typography

- Chinese interface: `"Microsoft YaHei", "PingFang SC", sans-serif`
- Numbers and prices: `"Cascadia Mono", "SFMono-Regular", Consolas, monospace`
- Headlines use 800-900 weight; body copy uses 400; data labels use 600.

## Motion

- Entrances: `expo.out`, `power3.out`, `back.out(1.25)`, 0.25-0.8 seconds.
- Ambient motion: deterministic fluid paths, slow scan and status pulse.
- Product images and text enter on separate vectors but settle into their static layout.
- No automatic product carousel and no continuous card movement.

## What NOT to Do

- Do not use a full-page purple gradient.
- Do not animate product cards while the user is reading them.
- Do not filter, tint, blur, crop, or distort product images.
- Do not hide business data behind decorative animation.
- Do not make motion required for navigation or comprehension.
