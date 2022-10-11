## 單詞查詢 API 模塊

## Development Guide
可在該模塊下添加自定義查詢API，繼承 `misc.AbstractQueryAPI`確保API能和插件兼容
之後將你的API 添加到當前目錄`__init.py` 中的 `apis` 列表中以便插件讀取，並且查詢返回結果滿足
```python
{
    'term': str,
    'definition': [str],
    'phrase': [(str,str)],
    'image': str,
    'sentence': [(str,str)],
    'BrEPhonetic': str,
    'AmEPhonetic': str,
    'BrEPron': str,
    'AmEPron': str
}

```
