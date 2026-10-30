# 字体

| 文件 | 说明 |
|---|---|
| `mashanzheng-slogan.woff` | 马善政楷书（Ma Shan Zheng）子集，只含标语「念有所感，必有回响。」用到的字，约 5 KB |
| `MaShanZheng-OFL.txt` | 字体许可证（SIL Open Font License 1.1），随字体一起分发 |

- 来源：Google Fonts 官方仓库 `https://raw.githubusercontent.com/google/fonts/main/ofl/mashanzheng/MaShanZheng-Regular.ttf`
- 原始文件 SHA256：`6d2546bb189c732a8ca29af9e22457b152387d158aa459e4ac2ce1e51788b7fb`（5,857,936 字节，2026-10-30 下载）
- 用在：`web/design-system.css` 的 `@font-face { font-family: "Echo Slogan" }`，仅 `.echo-slogan`。

改标语文字后，子集要重新生成，否则新字会退回系统楷体：

```sh
pip install fonttools
python3 - <<'PY'
from fontTools import subset
o = subset.Options(); o.flavor = 'woff'; o.layout_features = ['*']; o.name_IDs = ['*']
f = subset.load_font('MaShanZheng-Regular.ttf', o); s = subset.Subsetter(o)
s.populate(text='念有所感，必有回响。'); s.subset(f); subset.save_font(f, 'web/fonts/mashanzheng-slogan.woff', o)
PY
```
